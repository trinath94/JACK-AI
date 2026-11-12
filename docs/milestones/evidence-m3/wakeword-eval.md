# Wake-word evaluation (synthetic)

Engine `keyword-asr` as shipped (Silero VAD + Whisper tiny.en; biased pass + veto from sensitivity 0.5). 684 clips: 5 wake phrases × 8 voices × 2 speeds × 3 noise levels; 37 non-wake sentences (13 confusables) × 4 voices × 3 noise levels = 28.5 min of non-wake speech.

| Sensitivity | Miss rate | clean / 20 dB / 10 dB | False activations (everyday / confusable) | per hour of speech |
|---|---|---|---|---|
| 0.3 | 47.1% (113/240) | 33.8% / 37.5% / 70.0% | 1/444 (0 / 1) | 2.1 |
| 0.5 | 12.5% (30/240) | 7.5% / 7.5% / 22.5% | 20/444 (0 / 20) | 42.1 |
| 0.7 | 12.5% (30/240) | 7.5% / 7.5% / 22.5% | 20/444 (0 / 20) | 42.1 |
| 0.9 | 12.5% (30/240) | 7.5% / 7.5% / 22.5% | 20/444 (0 / 20) | 42.1 |

False-activation phrases at each sensitivity:

- **0.3**: "Jackson will join us later."
- **0.5**: "Hey Jake, how are you?", "Hey Zack, over here.", "Jackson will join us later.", "Jacqueline sent the report."
- **0.7**: "Hey Jake, how are you?", "Hey Zack, over here.", "Jackson will join us later.", "Jacqueline sent the report."
- **0.9**: "Hey Jake, how are you?", "Hey Zack, over here.", "Jackson will join us later.", "Jacqueline sent the report."

> Synthetic espeak-ng speech with white noise; not a field estimate. Real voices, accents, rooms and microphones need the acceptance test A on Windows (docs/architecture/ACCEPTANCE_TESTS.md).
