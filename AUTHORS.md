# Authors / 作者

- **Hungry-M** — initial implementation and maintenance.
- GitHub: <https://github.com/Hungry-M>

No email address is embedded in the binaries or package metadata. A GitHub
`noreply` address is fine for commits and open-source metadata; an Authenticode
code-signing certificate requires the CA to verify a real identity/contact, so a
`noreply` address cannot be used for the certificate itself.

The author string is used in:

- `packaging/version_gui.txt` (`CompanyName`, `LegalCopyright`, `Comments`)
- `packaging/version_installer.txt`
- `packaging/installer.py` (`AUTHOR`, `Publisher`)
- `LICENSE`

## Code signing / 数字签名

Release binaries are **unsigned by default** unless a code-signing certificate
is supplied. Windows SmartScreen will show "Unknown publisher" for unsigned
builds. See `packaging/sign.ps1` and the "Code signing" section of `README.md`
for the optional Authenticode flow; never commit a `.pfx` or its password.
