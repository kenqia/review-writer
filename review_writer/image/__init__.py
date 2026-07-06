"""Image adapters."""

from .base import ImageRequest, ImageResult
from .source_figure import SourceFigureAdapter
from .alibaba_image import AlibabaImageAdapter

__all__ = ["ImageRequest", "ImageResult", "SourceFigureAdapter", "AlibabaImageAdapter"]
