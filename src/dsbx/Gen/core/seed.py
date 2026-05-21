import numpy as np
from typing import Dict

class SeedManager:
    """Manages random number generator streams for reproducibility."""

    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self.seed_sequence: np.random.SeedSequence = np.random.SeedSequence(master_seed)
        self.streams: Dict[str, np.random.Generator] = {}
        self.seed_map: Dict[str, int] = {}

    def get_rng(self, stream_name: str) -> np.random.Generator:
        """Get a dedicated RNG for a specific purpose (e.g., arrivals, ptimes)."""
        if stream_name not in self.streams:
            stream_seed = self.seed_sequence.spawn(1)[0]
            self.streams[stream_name] = np.random.default_rng(stream_seed)
            entropy = stream_seed.entropy
            seed_int = int(entropy) if isinstance(entropy, int) else int(stream_seed.generate_state(1)[0])
            self.seed_map[stream_name] = seed_int
        return self.streams[stream_name]

    def get_seed_map(self) -> Dict[str, int]:
        """Return a map of stream names to their integer seeds."""
        return self.seed_map
