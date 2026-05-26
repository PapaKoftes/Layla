# Tools

This directory holds third-party executables bundled with Layla.

## nssm.exe

**NSSM (Non-Sucking Service Manager)** — wraps Layla as a Windows Service.

- License: MIT (public domain)
- Download: https://nssm.cc/release/nssm-2.24.zip
- Place the 64-bit `nssm.exe` from `win64/` in this directory

To install the service, run:
```powershell
powershell -File agent\install\install_service.ps1
```
