// The command that puts a public key on a remote machine.
//
// ssh-copy-id is used rather than a hand-rolled append: it creates ~/.ssh with the right
// mode, refuses to add a key twice, and is present on every machine that has an SSH
// client. It is run on the NASQuay host because that is where the key lives, and it will
// ask for the remote account's password once — which is exactly the thing being replaced.
export const sshCopyCommand = (
  publicPath: string,
  user = "USER",
  host = "HOST",
  port = 22,
) => {
  const portFlag = port && port !== 22 ? ` -p ${port}` : "";
  return `ssh-copy-id -i ${publicPath}${portFlag} ${user}@${host}`;
};
