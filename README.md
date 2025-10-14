# Vitaius Vestra System

End-to-end custom prosthetic creation pipeline for Vitaius Vestra Forms.

### Components
- **Blender Add-on** (`vitaius_vestra_designer.py`) — handles scan import, mirroring, chest fit, and STL exports.
- **Headless Processor** (`headless/process_cli.py`) — runs automated Blender sessions on the cloud.
- **API Server** (`server/api.py`) — manages app requests, order files, and communicates with headless Blender.
- **Web Portal** (`web/app.js`) — customer order tracking and 3D preview.
- **Worker** (`worker/entrypoint.sh`) — background jobs for rendering and uploads.
- **Docker Compose** — container orchestration for local or cloud deployment.

### Branding
All instances of *Sisters Prosthetics* have been migrated to **Vitaius Vestra**.
