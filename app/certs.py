"""
Reading an uploaded certificate, so the page can show what it is before it is trusted.

Nothing here is a secret: a certificate is the public half by definition, and an upload
carrying a private key is refused rather than stored. What this module produces is a
description — who it is for, who issued it, how long it lasts — and the PEM text the TLS
context is later built from.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

PEM_BEGIN = "-----BEGIN CERTIFICATE-----"
PEM_END = "-----END CERTIFICATE-----"


class CertError(Exception):
    """Anything that stopped an upload being accepted, in words fit for the page."""


@dataclass(frozen=True)
class Described:
    pem: str
    fingerprint: str
    subject: str
    issuer: str
    not_before: str
    not_after: str
    is_ca: bool


def _name(name: x509.Name) -> str:
    """The common name if the certificate has one, else the whole RFC 4514 string."""
    common = name.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return common[0].value if common else name.rfc4514_string()


def describe(text: str) -> Described:
    """Parse an uploaded PEM certificate, or say why it cannot be used.

    Only the first certificate in the text is described, but the whole chain is kept: a
    NAS behind an intermediate needs the intermediate as well as the root, and the
    description belongs to the certificate the administrator named the upload after.
    """
    body = text.strip()
    if "PRIVATE KEY" in body.upper():
        raise CertError(
            "That file contains a private key. Upload only the certificate — NASQuay "
            "never needs the private half of anything a NAS presents."
        )
    if PEM_BEGIN not in body:
        raise CertError(
            "That is not a PEM certificate. It must begin with "
            f"{PEM_BEGIN} — a .crt, .pem or .cer file in text form."
        )

    try:
        certificates = x509.load_pem_x509_certificates(body.encode())
    except (ValueError, TypeError) as exc:
        raise CertError(f"The certificate could not be read — {exc}") from exc
    if not certificates:
        raise CertError("No certificate was found in that file")

    first = certificates[0]
    try:
        is_ca = first.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        is_ca = False

    return Described(
        # Re-encoded from what was parsed rather than kept as typed, so whatever is stored
        # is a certificate and not the surrounding text of the file it was pasted from.
        pem="\n".join(c.public_bytes(Encoding.PEM).decode().strip() for c in certificates) + "\n",
        fingerprint=hashlib.sha256(first.public_bytes(Encoding.DER)).hexdigest(),
        subject=_name(first.subject),
        issuer=_name(first.issuer),
        not_before=first.not_valid_before_utc.isoformat(timespec="seconds"),
        not_after=first.not_valid_after_utc.isoformat(timespec="seconds"),
        is_ca=is_ca,
    )
