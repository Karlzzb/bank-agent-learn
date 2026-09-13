"""uvicorn 入口:bank_agent.run:app"""

from bank_agent.api import create_app
from bank_agent.composition import build_production

app = create_app(build_production())
