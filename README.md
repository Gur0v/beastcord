# beastcord

Run Discord on FreeBSD amd64 using the Linuxulator. Installs under your
home directory, with Equicord enabled by default. Written in Python 3,
using only the standard library.

## Requirements

Enable the Linuxulator and mount its proc, sys and shm filesystems first.
Install Python 3, fetch, and the RL9 Linux desktop libraries. Run
`./beastcord --doctor` to check mounts and list missing packages.
Dependencies are not installed automatically.

X11 is the default. Window detection uses xprop, with xwininfo as a
fallback. wmctrl is optional and is used to activate an existing window.
The graphics workaround also needs `/compat/linux/usr/bin/gcc`.

## Install

Run as your desktop user, not root:

```sh
./beastcord --doctor
./beastcord --install
$HOME/.local/bin/beastcord
```

Add `$HOME/.local/bin` to your PATH if needed. Installation also creates
a desktop entry. To install without Equicord:

```sh
./beastcord --install --vanilla
```

## Usage

Close Discord before updating, repairing, or rolling back.

```sh
beastcord                         # launch
beastcord --update                # update, keeping the current mode
beastcord --update --equicord     # switch to Equicord
beastcord --update --vanilla      # switch to vanilla
beastcord --repair-equicord       # reinstall Equicord on a staged copy
beastcord --rollback              # return to the previous version
beastcord --doctor                # check the installation
```

Normal launch does not download or patch anything. Failed staging leaves
the active version unchanged. Old versions are kept, not removed automatically.
Rollback changes the managed application files, not your Discord profile
or updates made by Discord itself.

To use a local Discord archive, add `--archive /path/to/client.tar.gz`
to the install or update command.

## Troubleshooting

For native Wayland:

```sh
BEASTCORD_OZONE_PLATFORM=wayland beastcord
```

Close existing clients manually when using Wayland. Window detection and
recovery are only available on X11. X11 recovery can stop windowless
Discord processes owned by your user, including clients started elsewhere.

For graphics problems, close Discord and try software rendering:

```sh
BEASTCORD_SOFTWARE_RENDERING=1 beastcord --launch
```

Startup output is saved to `~/.local/state/beastcord/startup.log` and
`startup.log.1`, limited to 512 KiB each. Check logs for private information
before sharing them.

To replace only the installed script, run this from the source directory
with Discord closed:

```sh
install -m 700 beastcord "$HOME/.local/bin/beastcord"
```

## Files

- `~/.local/bin/beastcord`: installed command.
- `~/.local/share/beastcord/`: versions and current/previous links.
- `~/.local/state/beastcord/`: logs and graphics cache.

Data and state paths respect `XDG_DATA_HOME` and `XDG_STATE_HOME`.
The existing Discord profile is used. Do not share it between running clients.

## Limitations

Discord runs with Chromium sandboxing disabled for Linuxulator compatibility.
Downloads use HTTPS but are not pinned or independently verified. Equicord
installation downloads and runs the Equilotl CLI as your user.

Screen sharing, audio, and hardware acceleration depend on your setup.
There is no uninstall command. Review the paths above before removing files,
and keep your Discord profile separate from application cleanup.

## Tests

```sh
sh -n beastcord-launcher
sh tests.sh
```

Tests do not launch a real Discord client.

## License

Licensed under the [BSD 2-Clause License](LICENSE).
