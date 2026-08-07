"""Shared array type aliases.

The glossary in docs/ARCHITECTURE.md section 2 defines the data objects.
Modules in core, pool, and providers import these aliases, and array
shapes stay documented by the type annotations.
"""

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]
IntArray = NDArray[np.int64]

# Batched embedding output: shape (B, d), each row unit-norm float32.
Vectors = NDArray[np.float32]
