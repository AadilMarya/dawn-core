# Sound design doctrine

## Start with the role

- Decide what the sound must do before choosing a device: sub, body, texture, transient,
  lead, pad, or effect.
- One sound can cover one role well. Layer only when you need two roles from one part.

## Subtractive synthesis

- Start with a simple waveform: sine for sub, saw for brightness, square for hollow body,
  triangle for softness.
- Shape amplitude first with the ADSR. A short attack and medium decay reads as plucked; a
  slow attack and long release reads as a pad.
- Filter after the oscillator. Low-pass for warmth, high-pass for thinness, resonance for
  character.
- Modulate one thing at a time: filter cutoff, pitch, pulse width or amplitude.

## FM and wavetables

- FM is for metallic, bell and harmonic motion. Keep the modulator ratio simple (1:1, 1:2,
  1:3) and modulate the index, not the carrier.
- Wavetables are for motion. Automate the wavetable position slowly; a static wavetable is
  just a waveform.
- Resample a complex patch when it is right. A committed sample is easier to arrange than a
  live patch.

## Samplers and drums

- Tune drums to the key when they have pitch. Check the fundamental against the bass.
- Layer a transient (click, hat, snap) with a body (kick, tom, sub) and high-pass the
  transient layer.
- Shorten releases on drums so they do not overlap the next hit.
- Use velocity and slight timing variation to avoid a mechanical grid.

## Space and character

- Add saturation before reverb, not after, when you want the reverb to sit behind the sound.
- Keep effects in parallel when you want to preserve the dry transient.
- A little noise, drift or pitch instability makes a synthetic part feel alive.
