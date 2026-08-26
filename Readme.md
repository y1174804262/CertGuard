# CertGuard

## Repository Structure

```text
.
├── CertGuard/
│   ├── CertGraph_PKI_Node/              # X.509 certificate and CRL structure graph
│   ├── CertGraph_RFC_Node/              # RFC parsing and document graph construction
│   ├── CertGraph_RFC2Certificate/       # Paragraph-to-PKI-entity linking
│   ├── CertRetrieve_Analyze_Verify/     # Retrieval, analysis, and verification
│   ├── config/                          # LLM and Neo4j configuration
│   ├── data/                            # Specifications and intermediate data
├── RFCScope-main/                       # RFCScope baseline
├── docs/                                # Documentation and figures
└── README.md
```

## Requirements

- Python 3.10 or later
- Neo4j 5.x
- An LLM service compatible with the OpenAI API

Install the main dependencies:

```bash
python -m pip install openai httpx neo4j tqdm tiktoken beautifulsoup4
```
