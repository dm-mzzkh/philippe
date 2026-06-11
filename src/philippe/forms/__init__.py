"""Form definition: parse and validate a ``form.yaml`` into typed objects."""

from .errors import FormError
from .loader import load_form
from .models import FieldSpec, FormSpec

__all__ = ["FormError", "FieldSpec", "FormSpec", "load_form"]
