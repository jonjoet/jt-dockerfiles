"""Thin Streamlit view; every navigation widget lives outside a form."""
from pathlib import Path
from functools import partial
import streamlit as st

from quickalign import jobs
from quickalign.errors import QuickalignError, ValidationError
from .config import UiConfig
from .paths import Selection, browse, label, redact
from .service import GATE, ReadRow, Source, Submission, initialize, submit


def file_selector(config, key, title, kind):
    st.markdown(f'**{title}**')
    mode = st.radio(f'{title} source', ['Server file', 'Upload'], horizontal=True, key=f'{key}_mode')
    if mode == 'Upload':
        upload = st.file_uploader(title, key=f'{key}_upload',
                                  max_upload_size=config.max_upload_bytes // 1024**2)
        return Source('upload', upload=upload) if upload is not None else None
    with st.expander(f'Browse {title}', expanded=f'{key}_selected' not in st.session_state):
        root = st.selectbox('Input root', range(len(config.input_roots)),
                            format_func=lambda n: f'Input {n + 1}', key=f'{key}_root')
        directory_key = f'{key}_directory_{root}'
        relative = st.session_state.get(directory_key, '.')
        here = Selection(root, relative)
        st.caption(label(here))
        try:
            entries = browse(config, here, kind)
        except ValidationError as error:
            st.error(redact(error))
            entries = []
        if relative != '.' and st.button('Up', key=f'{key}_up'):
            st.session_state[directory_key] = str(Path(relative).parent)
            st.rerun()
        directories = [e for e in entries if e[1]]
        selected_dir = st.selectbox('Subdirectory', [None] + directories,
                                    format_func=lambda e: e[0] if e else 'Choose directory',
                                    key=f'{key}_subdir_{root}_{relative}')
        if st.button('Open directory', disabled=selected_dir is None, key=f'{key}_open'):
            st.session_state[directory_key] = selected_dir[2].relative
            st.rerun()
        files = [e for e in entries if not e[1]]
        selected = st.selectbox('File', [None] + files,
                                format_func=lambda e: e[0] if e else 'Choose file',
                                key=f'{key}_file_{root}_{relative}')
        if st.button('Use file', disabled=selected is None, key=f'{key}_use'):
            st.session_state[f'{key}_selected'] = selected[2]
            st.rerun()
    selection = st.session_state.get(f'{key}_selected')
    if selection is not None:
        st.caption(f'Selected: {label(selection)}')
        if st.button('Clear selection', key=f'{key}_clear'):
            st.session_state.pop(f'{key}_selected', None)
            st.rerun()
        return Source('server', selection=selection)
    return None


def _clear_selector(prefix):
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]


def render_new(config):
    st.header('New bundle')
    st.caption('Choose mounted server files for large inputs. Uploads are intended for smaller files.')
    a, b = st.columns(2)
    with a:
        reference = file_selector(config, 'reference', 'Reference FASTA', 'reference')
    with b:
        annotation = file_selector(config, 'annotation', 'Annotation GFF/GFF3', 'annotation')
    if 'row_ids' not in st.session_state:
        st.session_state.row_ids = [0]
        st.session_state.next_row_id = 1
    rows = []
    for row_id in st.session_state.row_ids:
        key = f'read_{row_id}'
        with st.container(border=True):
            st.subheader(f'Read group {row_id + 1}')
            tech = st.selectbox('Technology', ['Illumina', 'Nanopore'], key=f'{key}_tech')
            layout = 'single'
            paired = False
            if tech == 'Illumina':
                paired = st.radio('Layout', ['Single', 'Paired'], horizontal=True, key=f'{key}_layout') == 'Paired'
            if not paired:
                _clear_selector(f'{key}_r2')
                st.session_state.pop(f'{key}_interleaved', None)
            columns = st.columns(2)
            with columns[0]:
                read1 = file_selector(config, f'{key}_r1', 'R1 / reads' if paired else 'Reads', 'reads')
            read2 = None
            if paired:
                with columns[1]:
                    interleaved = st.checkbox('Interleaved pairs in one file', key=f'{key}_interleaved')
                    if interleaved:
                        _clear_selector(f'{key}_r2')
                        st.caption('R2 is disabled; alternating mates are read from R1.')
                        layout = 'interleaved'
                    else:
                        read2 = file_selector(config, f'{key}_r2', 'R2', 'reads')
                        layout = 'paired'
            default_label = ''
            if read1:
                default_label = Path(read1.selection.relative).name if read1.kind == 'server' else read1.upload.name
            group_label = st.text_input('Track label (optional)', key=f'{key}_label') or default_label
            rows.append(ReadRow(group_label, tech.lower(), layout, read1, read2))
            if st.button('Remove read group', key=f'{key}_remove'):
                st.session_state.row_ids = [i for i in st.session_state.row_ids if i != row_id]
                _clear_selector(key + '_')
                st.rerun()
    if st.button('Add read group'):
        st.session_state.row_ids = [*st.session_state.row_ids, st.session_state.next_row_id]
        st.session_state.next_row_id += 1
        st.rerun()
    name = st.text_input('Sample name', value='sample', key='sample_name')
    threads = st.number_input('Threads', min_value=2, max_value=config.max_threads,
                               value=min(4, config.max_threads), step=1)
    with st.expander('Advanced'):
        sort_memory = st.selectbox('Sort memory per worker', ['256M', '512M', '1G', '2G'])
        keep_work = st.checkbox('Keep work files')
        st.caption('The container memory ceiling is set by the operator at startup.')
    if st.button('Build bundle', type='primary'):
        try:
            request = Submission(reference, annotation, tuple(rows), name, int(threads), sort_memory, keep_work)
            with st.spinner('Building bundle. Refreshing this page does not cancel the server job.'):
                result = submit(config, request)
            st.session_state.current_job = result.job_id
        except (QuickalignError, OSError, ValueError) as error:
            st.error(redact(error))


def render_result(config, item, prefix):
    job_id = item['job_id']
    st.write(f"{redact(item.get('name', job_id))} — {item['display_status'].replace('_', ' ').title()}")
    st.caption(job_id)
    for warning in item.get('warnings', []):
        if isinstance(warning, dict):
            st.warning(redact(f"{warning.get('group_label', '')}: {warning.get('input_name', '')}: {warning.get('message', '')}"))
    for track in item.get('tracks', []):
        if isinstance(track, dict):
            st.write(f"{redact(track.get('label', 'Track'))}: {track.get('mapped', 0)} mapped / {track.get('total', 0)} records")
            if track.get('zero_mapped'):
                st.warning('No reads mapped in this track; its valid BAM is retained.')
    if item.get('failure'):
        st.error(redact(item['failure'].get('message', 'Job failed; inspect mounted logs.')))
    if not item.get('bundle_available'):
        if item.get('validation_error'):
            st.error(redact(item['validation_error']))
        return
    output = config.output_root / job_id
    st.success(f"Bundle available in the output mount: {job_id}/{item['bundle']}")
    if item.get('export_display_status') in {'failed', 'interrupted'}:
        st.warning(f"ZIP export {item['export_display_status']}. The completed bundle remains available.")
    try:
        size = item['bundle_size_bytes']
        st.caption(f"Bundle assets: {size / 1024**2:.1f} MiB (recorded at creation)")
        archive = item.get('archive_name')
        if archive:
            st.caption(f"ZIP in the output mount: {job_id}/{archive}")
        if archive and item['archive_size_bytes'] <= config.max_download_bytes:
            st.download_button(
                'Download ZIP', partial(jobs.download_archive_bytes, output, config.max_download_bytes),
                file_name=archive, mime='application/zip', key=f'{prefix}_download', on_click='ignore',
            )
        else:
            if item.get('export_status') == 'completed':
                st.info('The completed ZIP exceeds the browser download limit or is unavailable. Retrieve the bundle from the mounted output folder.')
            elif size > config.max_download_bytes:
                st.info('This bundle exceeds the browser download limit. Retrieve its directory from the mounted output folder.')
            elif st.button('Prepare ZIP download', key=f'{prefix}_export'):
                # Serialize exports against submissions and other exports.
                if not GATE.lock.acquire(blocking=False):
                    st.info('Another job is running. Try again when it finishes.')
                else:
                    try:
                        GATE.active_job_id = job_id
                        with st.spinner('Preparing ZIP'):
                            jobs.export_zip(output)
                    finally:
                        GATE.active_job_id = None
                        GATE.lock.release()
                    st.rerun()
    except (QuickalignError, OSError, ValueError) as error:
        st.error(redact(error))


def main():
    st.set_page_config(page_title='quickalign', layout='wide')
    st.title('quickalign')
    st.write('Align Illumina and Nanopore reads against one reference, then open the bundle in JBrowse Desktop.')
    try:
        config = UiConfig.load()
        initialize(config)
    except (QuickalignError, OSError, ValueError) as error:
        st.error(redact(error))
        return
    render_new(config)
    results = jobs.discover_jobs(config.output_root, GATE.active_job_id)
    current = st.session_state.get('current_job')
    if current:
        st.header('Current result')
        for item in results:
            if item['job_id'] == current:
                render_result(config, item, 'current')
    st.header('Previous results')
    for item in results:
        if item['job_id'] != current:
            with st.expander(item['job_id']):
                render_result(config, item, item['job_id'])
