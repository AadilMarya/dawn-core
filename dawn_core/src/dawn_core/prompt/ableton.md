# Ableton Live

## The two views

- **Session view** holds clip slots and scenes. Use it to build and audition loops.
- **Arrangement view** is the timeline. Use it to arrange the track.
- A clip lives in one slot. Firing a slot launches its clip; firing a scene launches the
  whole row.

## Indices and names

- Every index is 0-based. Track 0 is the first track; scene 0 is the first scene; the first
  device on a track is device 0.
- Return tracks are indexed separately. Use the return-track tools for them.
- Prefer names in your report, but use indices in tool arguments.

## Clips and notes

- Clip length and note positions are in beats. In 4/4, one bar is 4 beats.
- MIDI pitch 60 is middle C. Velocity ranges from 1 to 127.
- A note has a pitch, start, duration, velocity and mute flag. Keep notes inside the clip
  length.

## Devices

- A track's devices are a chain in order. Device 0 is the first device.
- "Device On" is always parameter 0. Use it to switch a device on or off.
- Load devices from the browser by name, for example `Operator`, `Wavetable`, `Drum Rack`,
  `Reverb`, `EQ Eight`, `Compressor`.
- Parameter values are normalised to each device's reported minimum and maximum.

## Tracks

- MIDI tracks hold instruments and MIDI clips. Audio tracks hold audio clips and effects.
- Return tracks hold shared effects. The master track holds the final bus.
- Arm a track before recording. Mute and solo are mixer states, not arrangement edits.

## Working safely

- Read the Set before you change it. `get_session` is cheap.
- One change at a time, then read it back.
- Destructive actions: deleting a track, a clip or notes. Confirm the target first.
