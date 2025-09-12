import os


def extract_aem_fields_from_description(description: str, llm) -> dict:
    prompt = f"""
Extract the following fields from this text and return ONLY a JSON object with these keys:
- aem_service
- env_type
- aem_tier (use 'publish' if text mentions 'Publish deployment', 'author' for 'Author deployment')
- cluster
- aem_program_id (numeric part from aem_service, e.g., 55671 from cm-p55671-e392469)
- program
- namespace
- aem_release_id

If you show JSON, put it inside a ```json code block and do not add any extra commentary outside it.

Text:
{description}
"""
    import json, re
    content = llm.call(prompt)

    def ensure_keys(d: dict) -> dict:
        for k in [
            "aem_service","env_type","aem_tier","cluster","aem_program_id",
            "program","namespace","aem_release_id"
        ]:
            d[k] = (d.get(k) or "")
        return d

    # 1) Try to extract from fenced ```json block first
    try:
        m_block = re.search(r"```\s*json\s*([\s\S]*?)```", content, re.IGNORECASE)
        if m_block:
            json_text = m_block.group(1).strip()
            parsed = json.loads(json_text)
            return ensure_keys(parsed)
    except Exception:
        pass

    # 2) Try non-greedy brace match for the first JSON object
    try:
        m_obj = re.search(r"\{[\s\S]*?\}", content)
        if m_obj:
            json_text = m_obj.group(0)
            parsed = json.loads(json_text)
            return ensure_keys(parsed)
    except Exception as e:
        parse_error = str(e)
    else:
        parse_error = "No JSON braces found"

    # 3) Heuristic fallback extraction
    desc = description or ""
    aem_service = ""
    m = re.search(r"\bcm-p\d+-e\d+\b", desc)
    if m:
        aem_service = m.group(0)
    env_type = ""
    if re.search(r"\bprod\b", desc, re.IGNORECASE):
        env_type = "prod"
    elif re.search(r"\bstage|stg\b", desc, re.IGNORECASE):
        env_type = "stage"
    elif re.search(r"\bdev|development\b", desc, re.IGNORECASE):
        env_type = "dev"
    aem_tier = ""
    if re.search(r"Publish deployment", desc, re.IGNORECASE):
        aem_tier = "publish"
    elif re.search(r"Author deployment", desc, re.IGNORECASE):
        aem_tier = "author"
    elif re.search(r"dispatcher", desc, re.IGNORECASE):
        aem_tier = "dispatcher"
    cluster = ""
    m_cluster = re.search(r"\bethos\S+\b", desc, re.IGNORECASE)
    if m_cluster:
        cluster = m_cluster.group(0)
    namespace = ""
    m_ns = re.search(r"\bns-[\w-]+\b", desc)
    if m_ns:
        namespace = m_ns.group(0)
    aem_release_id = ""
    m_rel = re.search(r"\bcm-p\d+-e\d+\b", desc)
    if m_rel:
        aem_release_id = m_rel.group(0)
    aem_program_id = ""
    m_prog = re.search(r"cm-p(\d+)-e\d+", aem_service or "")
    if m_prog:
        aem_program_id = m_prog.group(1)
    program = ""

    return {
        "aem_service": aem_service,
        "env_type": env_type,
        "aem_tier": aem_tier,
        "cluster": cluster,
        "aem_program_id": aem_program_id,
        "program": program,
        "namespace": namespace,
        "aem_release_id": aem_release_id,
        "_debug_raw_llm": content,
        "_debug_parse_error": parse_error,
    }