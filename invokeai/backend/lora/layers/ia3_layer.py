from typing import Dict, Optional

import torch

from invokeai.backend.lora.layers.lora_layer_base import LoRALayerBase


class IA3Layer(LoRALayerBase):
    """IA3 Layer

    Example model for testing this layer type: https://civitai.com/models/123930/gwendolyn-tennyson-ben-10-ia3
    """

    def __init__(self, weight: torch.Tensor, on_input: torch.Tensor, bias: Optional[torch.Tensor]):
        super().__init__(alpha=None, bias=bias)
        self.weight = torch.nn.Parameter(weight)
        self.on_input = torch.nn.Parameter(on_input)

    def rank(self) -> int | None:
        return None

    @classmethod
    def from_state_dict_values(
        cls,
        values: Dict[str, torch.Tensor],
    ):
        bias = cls._parse_bias(
            values.get("bias_indices", None), values.get("bias_values", None), values.get("bias_size", None)
        )
        layer = cls(
            weight=values["weight"],
            on_input=values["on_input"],
            bias=bias,
        )
        cls.warn_on_unhandled_keys(
            values=values,
            handled_keys={
                # Default keys.
                "bias_indices",
                "bias_values",
                "bias_size",
                # Layer-specific keys.
                "weight",
                "on_input",
            },
        )
        return layer

    def get_weight(self, orig_weight: torch.Tensor) -> torch.Tensor:
        weight = self.weight
        if not self.on_input:
            weight = weight.reshape(-1, 1)
        return orig_weight * weight
