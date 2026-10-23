---
license: apache-2.0
base_model: Qwen/Qwen2.5-1.5B-Instruct
library_name: transformers
pipeline_tag: text-generation
language:
- en
tags:
- geoai
- outdoor-activity
- small-language-model
- hackathon
---

# OutdoorWise AI: Qwen2.5-1.5B-Instruct (unmodified)

Model repository for the **OutdoorWise AI** entry to the GeoAI Hackathon 2026 (CSRE, IIT Bombay).

## Base model
[Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), 1.5B parameters, Apache-2.0.

## Changes
**None.** The weights are the base model's, with no fine-tuning. This repository exists so the assistant loads
from this repo with `from_pretrained(...)`, as the rulebook requires.

## Intended use
Inside the OutdoorWise AI pipeline, the model does two jobs only:
1. extracts the activity, place and radius from messy questions when simple rules fail (output is validated against the question);
2. writes the final recommendation **from facts fetched live** (weather, air quality, OpenStreetMap, routing).

It is not used as a source of weather or geographic knowledge. A grounding check rejects any answer containing
numbers that are not in the fetched facts.

## Usage
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
tok = AutoTokenizer.from_pretrained("YOUR_USERNAME/outdoorwise-qwen2.5-1.5b")
model = AutoModelForCausalLM.from_pretrained("YOUR_USERNAME/outdoorwise-qwen2.5-1.5b")
```

## Limitations
Small models can make mistakes in free text. Recommendations are general guidance, not medical or safety advice.

## Data sources used by the full system
OpenStreetMap (Overpass, Nominatim; © OpenStreetMap contributors), Open-Meteo (forecast, air quality), OSRM.

Code: https://github.com/YOUR_USERNAME/OutdoorWiseAI
