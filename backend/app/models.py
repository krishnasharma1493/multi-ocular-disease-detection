# Import every table model here so create_all() knows about it
from app.modules.reviews.models import Review  # noqa: F401
from app.modules.screenings.models import Screening  # noqa: F401
from app.modules.users.models import User  # noqa: F401
