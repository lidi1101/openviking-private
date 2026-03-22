# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Honor HISP VLM Provider implementation.

Uses llm_resquest.py's send_llm_request function to call Honor HISP LLM service.
All connection parameters are hardcoded in llm_resquest.py.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Union

from ..base import VLMBase


class HonorHISPVLM(VLMBase):
    """
    Honor HISP VLM Provider.

    This provider uses the send_llm_request function from llm_resquest.py
    to call Honor's HISP LLM service. All connection parameters are
    hardcoded in llm_resquest.py, not in configuration.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Import here to avoid circular imports and ensure correct path resolution
        import sys
        from pathlib import Path

        # Add project root to path if not already there
        project_root = Path(__file__).parent.parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from llm_resquest import send_llm_request

        self._send_request = send_llm_request

    def _call_llm(self, prompt: str) -> str:
        """Call LLM using send_llm_request function."""
        # Note: llm_resquest.py's send_llm_request returns the final text directly
        # We pass the prompt as content parameter
        return self._send_request(content=prompt, prompt="")

    async def _call_llm_async(self, prompt: str) -> str:
        """Async wrapper for send_llm_request."""
        # Run the sync function in a thread pool since send_llm_request is synchronous
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._call_llm, prompt)

    def get_completion(self, prompt: str, thinking: bool = False) -> str:
        """Get text completion synchronously."""
        return self._call_llm(prompt)

    async def get_completion_async(
        self, prompt: str, thinking: bool = False, max_retries: int = 0
    ) -> str:
        """Get text completion asynchronously."""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return await self._call_llm_async(prompt)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)

        if last_error:
            raise last_error
        raise RuntimeError("Unknown error in async completion")

    def get_vision_completion(
        self,
        prompt: str,
        images: List[Union[str, Path, bytes]],
        thinking: bool = False,
    ) -> str:
        """Get vision completion.

        Note: Honor HISP LLM service may not support vision input directly.
        This implementation ignores images and only processes the text prompt.
        If vision support is needed, consider implementing image-to-text conversion.
        """
        # TODO: Implement vision support if HISP service supports it
        # For now, just process the text prompt
        return self._call_llm(prompt)

    async def get_vision_completion_async(
        self,
        prompt: str,
        images: List[Union[str, Path, bytes]],
        thinking: bool = False,
    ) -> str:
        """Get vision completion asynchronously."""
        # TODO: Implement vision support if HISP service supports it
        # For now, just process the text prompt
        return await self._call_llm_async(prompt)

    def is_available(self) -> bool:
        """Check if available.

        Always returns True since all parameters are hardcoded in llm_resquest.py.
        Actual availability is determined at request time.
        """
        return True
