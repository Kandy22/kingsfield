# [Project Name] — A Drone That Listens, Looks, and Sings Back

This project is a small autonomous drone built to perceive the people and devices around it and respond with sound. It sees faces through an ESP32-CAM and a Raspberry Pi 5 running OpenCV, and when it recognizes someone, it answers them — with a theme song, a spoken message, a flash of light. The drone is an instrument as much as it is a machine: a study in what it means for a flying sensor to know you, and to greet you.

A second layer extends the work into the audio domain. Drawing on published research into adversarial audio — Carlini's targeted attacks on speech recognition, the Dolphin Attack ultrasonic injection technique, psychoacoustic hiding, and Shazam-style fingerprinting in reverse — the drone can transmit signals that nearby phones interpret as commands, causing them to play media, respond to messages, or trigger ambient effects. This capability is deployed only with opt-in consent from participants and only within a controlled demonstration setting. The point is not to weaponize these techniques but to make them legible: to let an audience see and hear the surfaces by which their devices already listen, and to ask what it means that those surfaces exist.

The hardware is deliberately approachable — ESP32-CAM, FT232RL programmer, an SG-90 pan/tilt rig, an MB102 power module, 18650 cells, an iOS companion app (iRobbie-A) — all components anyone could assemble at a workbench. The software stack combines computer vision (OpenCV face recognition), audio fingerprinting, GPS tracking, and targeting logic for the pan-tilt. Conceptually it sits downstream of *Artificial Senses* (Kim Albrecht / metaLAB at Harvard) and projects like Qualcomm's DronaRhythm: not asking whether drones can do more, but asking what they perceive, what they decide to do with that perception, and where the boundary sits between a machine that responds to its environment and one that acts on the people inside it.

---

## Reference Notes

### Hardware
- Raspberry Pi 5 (main compute)
- ESP32-CAM — WiFi/BT/BLE video module
- FT232RL FTDI Mini USB — for flashing the ESP32-CAM
- Mini Pan/Tilt Platform with 2x SG-90 servos
- MB102 Breadboard Power Supply Module
- 18650 Battery Holder + 2x 18650 cells (or 4x AA alternative)
- iRobbie-A iOS App (companion control)

### Software / Algorithms
- **Vision:** OpenCV (facial recognition)
- **Audio:** Dolphin Attack, Carlini adversarial audio attacks, psychoacoustic hiding, reverse-Shazam fingerprinting
- **Location:** GPS tracking
- **Targeting:** pan-tilt aiming logic
- **Audio fingerprinting** (content-based compact signatures)

### Conceptual / Reference Works
- *Artificial Senses* — Kim Albrecht, metaLAB at Harvard
- *DronaRhythm* — Qualcomm Developer Network (Achinthya Soordelu, Homer Baker, Hima Tammineedi)
- *Defense Primer: Military Use of the Electromagnetic Spectrum*
- *An Industrial-Strength Audio Search Algorithm* (Shazam paper)
- *A Review of Algorithms for Audio Fingerprinting*
- Hiding data in sound (psychoacoustic steganography)
