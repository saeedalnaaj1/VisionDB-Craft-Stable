# Update report - VisionDB Craft Stable 3.6.0

Changes against 3.5.1:
- Setup: graphical wizard, automatic Python 3.12, quick-launch EXE (default), optional standalone EXE and installer, repair option, resumable/skip-if-current installs, plain-language errors. New files: setup_gui.py, tools/bootstrap.ps1, tools/make_launcher.py, tools/launcher_stub.py, tools/make_shortcut.ps1, tests/test_setup.py. setup_app.py was rewritten.
- Version: 3.5.1 -> 3.6.0 everywhere (package, project metadata, executable properties, installer, tests). Application code is otherwise unchanged.
- Documentation: README, SETUP-GUIDE, TESTING, BUILD and CHANGELOG rewritten for Stable; complete documentation (docs/VisionDB-Craft-Stable-Complete-Documentation-3.6.0.pdf) added. No AI/model/GPU content.

Verification limits: see TESTING.md. No Windows hardware was available when this was built.
