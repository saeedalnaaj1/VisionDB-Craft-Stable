"""Dataset engineering support for VisionDB Craft.

The desktop editor can still be used with ordinary images and folders.  This
package is activated only when a structured computer-vision dataset is opened.
"""

from imagecraft.dataset.models import Annotation, DatasetProject, DatasetRecord

__all__ = ["Annotation", "DatasetProject", "DatasetRecord"]
