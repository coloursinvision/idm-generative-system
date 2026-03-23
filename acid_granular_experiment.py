import numpy as np
import scipy.io.wavfile as wav

"""
UNDERGROUND DSP EXPERIMENT: ACID x GRANULAR
Target: Autechre-style 'Micro-Edit' and 'Grain-Cloud' processing.
Logic: 
1. Render Acid Sequence (303 Logic)
2. Apply Stochastic Granular Resampling (Stochastic Grain Cloud)
"""

class AcidDSPModel:
    def __init__(self, sample_rate=44100):
        self.sr = sample_rate
        self.current_f = 110.0
        self.phase = 0.0

    def process_sequence(self, notes, slides, accents, step_time):
        full_buffer = []
        for i in range(len(notes)):
            num_samples = int(self.sr * step_time)
            alpha = 1.0 - np.exp(-1.0 / (self.sr * 0.05)) if slides[i] else 1.0
            for _ in range(num_samples):
                self.current_f = (alpha * notes[i]) + (1.0 - alpha) * self.current_f
                self.phase += self.current_f / self.sr
                if self.phase > 1.0: self.phase -= 2.0
                sample = np.tanh(self.phase * (2.5 if accents[i] else 1.0))
                full_buffer.append(sample)
        return np.array(full_buffer)

class GranularIDMProcessor:
    def __init__(self, sample_rate=44100):
        self.sr = sample_rate

    def apply_autechre_cloud(self, input_signal, grain_size_ms=25, density=60):
        grain_len = int(self.sr * (grain_size_ms / 1000.0))
        output = np.zeros(len(input_signal))
        window = np.hanning(grain_len)
        num_grains = int((len(input_signal) / self.sr) * density)

        for _ in range(num_grains):
            # Stochastic grain selection and temporal jitter
            source_pos = np.random.randint(0, len(input_signal) - grain_len)
            target_pos = np.random.randint(0, len(input_signal) - grain_len)
            
            grain = input_signal[source_pos : source_pos + grain_len] * window
            output[target_pos : target_pos + grain_len] += grain
        return output

# --- EXECUTION ---
if __name__ == "__main__":
    sr = 44100
    acid_engine = AcidDSPModel(sr)
    glitch_fx = GranularIDMProcessor(sr)

    # 1. Generate Raw Acid Pattern (C2 to G2)
    notes = [65.4, 98.0, 130.8, 65.4, 49.0, 73.4, 98.0, 65.4]
    slides = [False, True, False, False, True, False, True, False]
    accents = [False, True, False, False, False, False, True, False]
    
    print("Step 1: Rendering Acid Sequence...")
    raw_acid = acid_engine.process_sequence(notes, slides, accents, 0.125)

    # 2. Apply IDM Granular Cloud (Resampling)
    print("Step 2: Applying Granular Deconstruction (Autechre-style)...")
    glitched_audio = glitch_fx.apply_autechre_cloud(raw_acid, grain_size_ms=35, density=80)

    # 3. Final Summing (Dry/Wet mix)
    final_mix = (raw_acid * 0.4) + (glitched_audio * 0.6)
    
    # 4. Normalize and Save
    final_mix = (final_mix / np.max(np.abs(final_mix)) * 32767).astype(np.int16)
    wav.write("autechre_acid_experiment.wav", sr, final_mix)
    
    print("Success: File 'autechre_acid_experiment.wav' generated.")
