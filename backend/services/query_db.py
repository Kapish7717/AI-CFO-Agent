import os
import json
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
import sqlite3
load_dotenv()

JINA_API_KEY = os.getenv("JINA_API_KEY", "")
