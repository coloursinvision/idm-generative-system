import numpy as np

"""
UNDERGROUND DSP MODELING SUITE
Target: TB-303 Acid behaviors & Detroit Chord Stacks
"""

class AcidDSPModel:
    def __init__(self, sample_rate=44100):
        self.sr = sample_rate

    def apply_303_slide(self, freq_sequence, slide_active, slide_time_ms=50):
        """
        Models nonlinear frequency transitions (Analog Glide).
        freq_sequence: Array of target frequencies (per step)
        slide_active: Boolean array (True if slide is active for step)
        """
        alpha = 1.0 - np.exp(-1.0 / (self.sr * (slide_time_ms / 1000.0)))
        smoothed_freqs = np.zeros(len(freq_sequence))
        
        current_f = freq_sequence[0]
        for i, target_f in enumerate(freq_sequence):
            if slide_active[i]:
                # Recursive filter for glide emulation
                current_f += alpha * (target_f - current_f)
            else:
                current_f = target_f
            smoothed_freqs[i] = current_f
        return smoothed_freqs

    def detroit_chord_stack(self, root_freq, chord_type='min9'):
        """Generates offsets for 'Parallel Pitch Shifting' typical in Techno"""
        intervals = {
            'min7': [1.0, 1.189, 1.498, 1.782],         # 0, 3, 7, 10 semitones
            'min9': [1.0, 1.189, 1.498, 1.782, 2.118]   # 0, 3, 7, 10, 14 semitones
        }
        return [root_freq * ratio for ratio in intervals[chord_type]]

    def apply_accent_saturation(self, signal, accent_enabled=False):
        """Emulates VCA Overdrive during Accented steps"""
        drive = 1.8 if accent_enabled else 1.0
        # Asymmetric tanh-based soft-clipping for analog warmth
        return np.tanh(signal * drive)

# Example Usage for Dataset Generation:
model = AcidDSPModel()
test_freqs = [110.0, 220.0, 165.0]
test_slides = [False, True, True]

# Compute glide curve for the oscillator
freq_curve = model.apply_303_slide(test_freqs, test_slides)
print(f"Calculated Pitch Curve (First 5 values): {freq_curve[:5]}")

