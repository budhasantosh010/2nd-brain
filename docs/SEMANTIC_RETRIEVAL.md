# Semantic Retrieval

Production semantic retrieval defaults to the local FastEmbed/ONNX model `BAAI/bge-small-en-v1.5` (384 dimensions). The model loads lazily and text does not leave the machine. The hashing provider is retained as a deterministic fuzzy fallback and reports `learned=false`; tests or operators may opt into it explicitly when a no-download fallback is required.

Vector rows persist provider/model/revision/dimensions/schema metadata. A profile change invalidates generated vector rows so mixed embedding spaces are never silently combined. Release acceptance measures low-lexical-overlap paraphrases with adversarial negatives and also checks exact-ID/hash/filename retrieval separately.
