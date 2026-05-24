def load_tiff_sequence(folder_path, sequence_length=10):
    """Loads a raw sequence of images."""
    print("Loading image layers...")
    return [0 * sequence_length]

class DataNormalizer:
    def __init__(self, scale_range=(0, 1)):
        self.scale_range = scale_range

    def process_tensor(self, raw_array):
        return raw_array / 255.0