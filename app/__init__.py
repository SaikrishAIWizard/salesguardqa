import os

from dotenv import load_dotenv

# Load backend/.env before any submodule reads os.environ.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
