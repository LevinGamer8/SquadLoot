# Third-party components (SquadLoot 1.5.4)

SquadLoot uses two MIT-licensed engines with permission from their
respective open-source licenses. This does not imply affiliation,
endorsement or anti-cheat approval from Epic Games.

## Replay analysis

Project: https://github.com/LED-N/Fortnite-ChestCounter
Release: https://github.com/LED-N/Fortnite-ChestCounter/releases/tag/v1.4.0
Asset: ChestCounter.exe
Bytes: 37959310
SHA256: 9da628f09f8e1d8545ad7f34ecb65fee48acd856bcce8c809f1e0eb8a4e5c8c7
License: MIT; original author LED-N, copyright (c) 2026 LED-N.
The original CLI is executed headlessly with --once, --data, --demos.

## Live analysis

Project: https://github.com/GabrielGzS/fortnite-visual-chest-counter
Release: https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/tag/v0.2.3
Asset: Fortnite-Visual-Chest-Counter-v0.2.3.zip
Bytes: 155755927
SHA256: a8c54d53842f640121df6fcf6be331be2941469c80e7880aee6d37cfaafd7e3c
License: MIT; copyright and license terms in the upstream LICENSE.
SquadLoot extracts the original runtime Python, libraries and FFmpeg,
but does not run the third-party graphical interface. The headless
live --gui machine-readable stream supplies approx/certain counts.

## Security and limitations

- Official pinned GitHub releases only, verified HTTPS host redirect,
  exact SHA256 and size checks.
- Safe ZIP extraction rejects symlinks and traversal.
- Installed under %LOCALAPPDATA%\SquadLoot\engines with user privileges;
  neither binary lives in the 4MB SquadLoot Windows update ZIP.
- The binaries are third-party programs and may be unsigned. SHA256
  verifies the released bytes, not their ultimate safety.
- A user-calibrated German template from v1.5.3 can be imported locally.
  German live popup recognition is otherwise not verified.
- No Fortnite memory access, injection, or anti-cheat bypass.
- Refer to each upstream repository's LICENSE for full MIT license text.
