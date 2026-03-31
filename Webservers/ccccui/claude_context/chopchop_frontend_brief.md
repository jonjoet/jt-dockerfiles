# CHOPCHOP Web Frontend — Project Brief for Claude Code

## Goal

Build a simple web-based frontend that lets a non-technical lab user design Cpf1 (Cas12a) guide RNAs by filling in a form, without needing to touch a terminal. The backend is an existing CHOPCHOP Docker container running on a shared Azure VM.

## Context

- **CHOPCHOP** is an open-source (Apache 2.0) Python tool for CRISPR guide RNA design. Source: `https://bitbucket.org/valenlab/chopchop` (GitHub mirror: `https://github.com/Carl-labhub/chopchop-clone`)
- We use it specifically for **Cpf1/Cas12a** because Cas9 is toxic in our organism
- We have a **custom genome** added to CHOPCHOP for off-target analysis against our strain
- CHOPCHOP is already installed and working inside a **Docker container** on a shared **Azure VM**
- Currently only "superusers" comfortable with the CLI can design guides
- We need to make this accessible to a lab worker who has SSH key access to the VM but isn't comfortable using the terminal

## Architecture

```
[Her Windows laptop]                    [Azure VM]
                                        
  .bat shortcut                         Streamlit app (:8501)
    │                                       │
    ├─ opens SSH tunnel (port 8501)         ├─ serves form UI
    └─ launches browser to localhost:8501   ├─ calls: docker exec <container> chopchop.py ...
                                            ├─ parses TSV output
                                            └─ displays ranked guides in table
```

### Components to build

1. **Streamlit app** (`app.py`) — runs on the VM
2. **Windows `.bat` shortcut** — runs on her laptop
3. **Setup/install instructions** (`README.md`)

## Technical Details


### USER INPUT: current command for chopchop container

This is an example of the command I use to run the chopchop container. I guess it should switch to docker exec to run in an already running container.

```
docker run --rm -v $(pwd):/data --user $(id -u):$(id -g) chopchop:ATCC13032 chopchop.py -Target /data/example_target.fasta -F -G ATCC13032 -SC -scoringMethod KIM_2018 -T 3 -M TTTM --maxMismatches 3 -g 21 -t WHOLE --rm1perfOff -o example_dir > example_guides.tsv 2> python.err

```

we'll need to upload that target fasta and make the PAM a user-enterable field. length and number of mismatches, too. the modifiable fields (other than the input fasta, of course) should use the current values as defaults. the output names should default to the input filename plus a suffix. the output folders will have to be saved in the working directory of the streamlit container, if possible. 

### Streamlit App Requirements

- **Form fields:**
  - Target (text input) — gene name, genomic coordinates, or paste a DNA sequence
  - Input type selector: Gene name / Coordinates / Pasted sequence
  - Genome (dropdown, but may only have one option — the custom strain)
  - Guide length (default 23, range 20-25)
  - Max mismatches for off-targets (default 3, range 0-5)
  - PAM (default TTTN, option for TTTV)
  - Number of results to show
- **Output:** A sortable table of ranked guide RNAs with key columns
- **Download:** Button to export results as CSV
- **Error handling:** Show CHOPCHOP stderr clearly if a job fails
- The app should use `subprocess.run()` to call `docker exec` and capture stdout/stderr
- Job output should go to a temp directory that gets cleaned up
- Consider a spinner/progress indicator since CHOPCHOP can take a minute

### Windows .bat Shortcut

- Opens an SSH tunnel: `ssh -N -L 8501:localhost:8501 <user>@<vm_ip> -i <path_to_key>`
- Launches browser: `start http://localhost:8501`
- Should run the SSH tunnel in the background and keep the window open
- The user, VM IP, and key path should be clearly marked for customization
- Consider adding a check/retry if the tunnel fails

### Deployment on the VM

deleted deployment idea from AI chat to replace with user input. I want to use docker compose if at all possible. The idea would be for a streamlit container to somehow talk to a chop chop container and serve the output. i guess the challenge is running a command in one docker container from inside another. perhaps there's an alternative solution. the goal is to avoid installing anything on the host machine. 

## Things the implementer will need to customize

These values are specific to their environment and should be clearly marked with `# <-- CHANGE THIS` comments:

- Docker container name/ID
- Path to `chopchop.py` inside the container
- Custom genome identifier string
- VM IP address and SSH username (in the .bat file)
- Path to SSH private key on her Windows laptop
- Any additional CHOPCHOP arguments they always use

## Dependencies

figure these out again based on new architecture

## user input: important additional script
there's a script in claude context for taking a genbank and annotating it with the guides. please include functionality for optionally uploading a genbank alongside the fasta file (keep them separate to protect the integrity of the fasta sequence) to allow using this script and getting the output.