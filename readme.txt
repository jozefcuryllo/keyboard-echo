Keyboard Echo
===============

Reasoning
------------
It works even in a pure linux terminal.

Requirements
------------
1. OS: Linux with python3 and libasound2-dev
2. Audio: ALSA device ('pulse' recommended for mixing sounds with other applications)
3. Permissions: User must be in 'input' and 'audio' groups

One-time Setup
--------------
Run to configure group permissions rules:
  sudo usermod -aG input,audio $USER

*Restart your terminal after execution.

Installation
------------
  python3 -m venv .venv
  source .venv/bin/activate
  (venv) pip install -r requirements.txt

Usage
-----
Run as a regular user (DO NOT use sudo):
  (venv) python main.py

Choosing the device (-d):
- In GUI environments: Use '-d pulse' (default) or '-d pipewire'. The system sound server 
  controls the hardware, so you must route audio through it to mix with other apps.
- In pure TTY (Terminal): If you don't care about interference with other sounds 
  you can directly access ALSA device by arguments like '-d default:CARD=Generic_1'.
  (Check the list of available devices printed to the console on startup).

- Press keys to create an audio stream simulating sounds of mechanical keyboard.
- Use -o [filename.wav] argument to save the stream into the provided file.
- Use -p [name] to set the keyboard profile - appropriate samples will be downloaded from
  https://raw.githubusercontent.com/nicholastay/mechanical-sound Default: MXRed
- Press 'q' or Ctrl+C to stop and safely finalize the recorded WAV file.

AI Usage Restrictions
--------------------
Ingestion, training, processing, or any form of utilization of the code and assets within 
this repository by or for artificial intelligence (AI), machine learning models,
or code-generation utilities is strictly prohibited without explicit, written authorization 
from the author.