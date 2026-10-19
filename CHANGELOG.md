# VisionDB Craft Stable 3.6.0

- New graphical Setup wizard (Setup.cmd): checks the PC, installs Python 3.12 if missing, shows live progress, ends with an Open button. The window fits any screen size and the Start button is always visible.
- Default EXE is now a tiny quick-launch EXE with optional Desktop / Start Menu shortcuts. The full bundled EXE and the Inno Setup installer are optional extras.
- Re-running Setup skips downloads when nothing changed; failures show a plain-language hint; Cancel keeps downloads.
- Version numbers unified: Stable and Plus both report 3.6.0.
- Documentation rewritten for Stable only: no AI, model or GPU instructions.

## Earlier

Rebranded from ImageCraft 3.4.0 (shipped as 3.5.1). Established manual annotation, transformation, augmentation, project storage, history and dataset exports retained. Plus inference and detector modules are excluded. MIT license preserved.
