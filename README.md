# VibeDispatch

A central dashboard and workflow orchestration platform for managing GitHub repositories at scale with automated code quality checks and AI-powered remediation.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Overview

VibeDispatch orchestrates a multi-stage pipeline that combines automated code analysis ([VibeCheck](https://github.com/WolffM/vibecheck)) with GitHub Copilot for automated fixes, all managed through a unified web dashboard. It's designed for organizations managing multiple repositories that want automated quality checks coupled with human-controlled remediation.

### Core Workflow

```
Install VibeCheck -> Run Analysis -> Assign Copilot -> Review & Merge
     Stage 1            Stage 2         Stage 3          Stage 4
```

## Features

### Pipeline-Based Workflow

VibeDispatch organizes repository management into a 4-stage pipeline:

1. **Stage 1: Install** - Repos that need VibeCheck workflow installed
2. **Stage 2: Run** - Repos with VibeCheck installed, showing run status and commits since last run
3. **Stage 3: Assign** - VibeCheck issues ready to be assigned to GitHub Copilot (sorted by severity)
4. **Stage 4: Review** - Open PRs ready for review and merge (with inline diff viewing)

### Key Capabilities

- **Batch Operations** - Install VibeCheck, run workflows, or assign issues across multiple repos at once
- **GitHub Copilot Integration** - Automatically assign Copilot to fix VibeCheck-discovered issues
- **PR Management** - Review, approve, and merge PRs with inline diff viewing
- **Real-time Monitoring** - Track workflow runs and health status across all repositories
- **Smart Caching** - 5-minute TTL cache for efficient API usage
- **Parallel Execution** - ThreadPoolExecutor for concurrent API requests (up to 10 parallel)
- **URL Prefix Support** - Deploy behind edge routers (e.g., `hadoku.me/dispatch/*`)

## Architecture

### Technology Stack

**Backend:**

- Flask 3.0.0 (Python web framework)
- GitHub CLI (`gh`) for all GitHub operations
- ThreadPoolExecutor for parallelization
- In-memory caching with TTL

**Frontend:**

- Bootstrap 5.3.2 with dark theme
- Vanilla JavaScript (ES6, no build tools)
- Jinja2 templates

**Integrations:**

- [VibeCheck](https://github.com/WolffM/vibecheck) - GitHub Action for code quality analysis
- GitHub Copilot - AI-powered issue fixing
- GitHub API - Repository, issue, PR, and workflow management

### Project Structure

```
vibedispatch/
%%% app.py                    # Main Flask application (~660 lines)
%                             # Routes: dashboard, repo_detail, global_actions, healthcheck
%                             # 20+ API endpoints for pipeline management
%%% config.py                 # Configuration constants
%                             # CACHE_TTL, MAX_REPOS, VIBECHECK_WORKFLOW template
%%% requirements.txt          # Python dependencies
%%% services/
%   %%% __init__.py          # Service exports
%   %%% cache.py             # In-memory caching with TTL
%   %%% github_api.py        # GitHub CLI wrapper functions
%%% static/
%   %%% css/styles.css       # Dark theme styles
%   %%% js/
%       %%% utils.js         # Shared utilities (API calls, formatting, diff rendering)
%       %%% actions.js       # Common action functions
%       %%% global-actions.js # Pipeline stage logic
%%% templates/
%   %%% base.html            # Base layout with navigation
%   %%% dashboard.html       # Main repo grid view
%   %%% repo_detail.html     # Single repo dashboard
%   %%% global_actions.html  # Pipeline management interface
%   %%% healthcheck.html     # Workflow monitoring
%%% docs/planning/           # Vision and planning documents
```

## Prerequisites

- **Python 3.8+**
- **GitHub CLI (`gh`)** - [Install Guide](https://cli.github.com/)
- **GitHub Account** with Copilot access (for Copilot features)

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/WolffM/vibedispatch.git
   cd vibedispatch
   ```

2. **Create virtual environment**

   ```bash
   python -m venv .venv

   # Windows
   .venv\Scripts\activate

   # macOS/Linux
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Authenticate with GitHub CLI**

   ```bash
   gh auth login
   ```

5. **Run the application**

   ```bash
   python app.py
   ```

6. **Open in browser**
   ```
   http://localhost:5000
   ```

## Usage

### Dashboard (`/`)

The main dashboard shows all your repositories with their VibeCheck installation status. Click any repo to view details including issues, PRs, workflows, and run history.

### Global Actions (`/global-actions`)

The pipeline management interface with stage tabs:

- **Stage 1**: Select repos and click "Install VibeCheck" to add the workflow
- **Stage 2**: Run VibeCheck on repos, especially those with commits since the last run
- **Stage 3**: Assign Copilot to fix issues discovered by VibeCheck (sorted by severity)
- **Stage 4**: Review PRs created by Copilot, approve and merge them

### Health Check (`/healthcheck`)

Monitor workflow runs across all repositories with status indicators.

## API Endpoints

### Stage Management

| Endpoint             | Method | Description                                |
| -------------------- | ------ | ------------------------------------------ |
| `/api/stage1-repos`  | GET    | Get repos needing VibeCheck                |
| `/api/stage2-repos`  | GET    | Get repos with run status                  |
| `/api/stage3-issues` | GET    | Get assignable issues (sorted by severity) |
| `/api/stage4-prs`    | GET    | Get reviewable PRs                         |

### Workflow Control

| Endpoint                    | Method | Description                   |
| --------------------------- | ------ | ----------------------------- |
| `/api/install-vibecheck`    | POST   | Install VibeCheck workflow    |
| `/api/run-vibecheck`        | POST   | Trigger VibeCheck workflow    |
| `/api/run-full-pipeline`    | POST   | Install + trigger in sequence |
| `/api/workflow-status`      | POST   | Check latest run status       |
| `/api/global-workflow-runs` | GET    | Recent runs across all repos  |

### Issue & PR Management

| Endpoint              | Method | Description                   |
| --------------------- | ------ | ----------------------------- |
| `/api/assign-copilot` | POST   | Assign Copilot to an issue    |
| `/api/approve-pr`     | POST   | Approve a pull request        |
| `/api/mark-pr-ready`  | POST   | Mark draft PR as ready        |
| `/api/merge-pr`       | POST   | Merge a pull request (squash) |
| `/api/pr-details`     | POST   | Get full PR info + diff       |

### Utilities

| Endpoint           | Method | Description                  |
| ------------------ | ------ | ---------------------------- |
| `/api/clear-cache` | POST   | Clear vibecheck status cache |

## Configuration

Edit `config.py` to customize:

```python
CACHE_TTL = 300                    # Cache duration in seconds (5 min)
MAX_REPOS = 100                    # Max repos to fetch
MAX_CONCURRENT_REQUESTS = 10       # Parallel API requests
MAX_REPOS_FOR_STAGE = 15           # Max repos shown per stage
```

### Environment Variables

| Variable     | Description                         | Default      |
| ------------ | ----------------------------------- | ------------ |
| `URL_PREFIX` | URL prefix for proxied deployment   | `/dispatch`  |
| `FLASK_ENV`  | Set to `development` for debug mode | `production` |

## What is VibeCheck?

[VibeCheck](https://github.com/WolffM/vibecheck) is a GitHub Action that performs automated code quality analysis on your repositories. It creates issues with severity labels (`severity-high`, `severity-medium`, `severity-low`) that can then be assigned to GitHub Copilot for automated fixes.

## Future Vision

VibeDispatch is evolving toward a full **agentic workflow orchestration platform**. See [docs/planning/objective-to-task-pipeline.md](docs/planning/objective-to-task-pipeline.md) for the vision, which includes:

- **Objective to Task Pipeline**: Break high-level goals into atomic, agent-executable tasks
- **Multi-Agent Support**: Route work to the right agent (Copilot, Claude Code, Cursor, custom agents)
- **Context Bundling**: Package tasks with all necessary context so agents don't need to fetch more
- **Configurable Review Gates**: Different workflows for different task types
- **Cross-Repo Coordination**: Handle objectives spanning multiple repositories

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
