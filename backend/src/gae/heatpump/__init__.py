"""Heat-pump maths core.

Pure, typed functions with no network calls. Inputs are plain values; later layers feed them
from Gemini photo reads, the EPC API and weather data. Every number returned carries a range
or a confidence, because even government-trialled measured methods carry ~20% error.
"""
