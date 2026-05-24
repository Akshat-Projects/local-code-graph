class ConvLSTM2DPipeline:
    def __init__(self, filters=64, kernel_size=(3, 3)):
        self.filters = filters
        self.kernel_size = kernel_size

    def build_forward_pass(self, input_tensor):
        pass