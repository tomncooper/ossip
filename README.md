# OSSIP 
_A hub for Open Source Software Improvement Proposals_

[ossip.dev](https://ossip.dev/)

This repo holds a collection of scripts for making a more enriched version of the Improvement Proposals from various open source projects.
The only one currently supported is the [Apache Kafka](https://kafka.apache.org/) project's [Kafka Improvement Proposal (KIP)](https://cwiki.apache.org/confluence/display/kafka/kafka+improvement+proposals), but [Apache Flink](https://flink.apache.org/)'s [FLIP](https://cwiki.apache.org/confluence/display/FLINK/Flink+Improvement+Proposals)s are coming soon.

## Development

### Installation

This project uses [`uv`](https://docs.astral.sh/uv/) to manage dependencies. 
To install the necessary libraries run:

```bash
$ uv sync
```

### Downloading and processing KIP data

To download the Apache Kafka `dev` mailing list for the last year (longer periods can be set via the `--days` option), process the archives and download the KIP Wiki information from the confluence site; run the `init` command:

```bash
$ uv run python ipper/main.py kafka init --days 365
```

To update only the most recent month and add any new KIPs which have been posted since the last update run:

```bash
$ uv run python ipper/main.py kafka update
```

### Creating the standalone site

To create the standalone site html run the command below where the first argument is the kip mentions cache file produced by the step above and the second is the html output filepath:

```bash
$ uv run python ipper/main.py kafka output standalone dev/kip_mentions.csv index.html
```

## Deployment

A Github action (see `.github/publish.yaml`) will build and publish the site on every push to `main`. 
The site is automatically built and deployed every day at approximately 09:30 UTC.

