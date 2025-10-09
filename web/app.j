async function upload() {
  const mesh = document.getElementById('mesh').files[0];
  if(!mesh){ alert("Pick a mesh file"); return; }
  const side = document.querySelector('input[name="side"]:checked').value;
  const midlineX = parseFloat(document.getElementById('midlineX').value || "0");
  const offset = parseFloat(document.getElementById('offset').value || "2");

  const jszipUrl = "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js";
  const JSZip = (await import(jszipUrl)).default || window.JSZip;

  const zip = new JSZip();
  zip.file("mesh_breast.stl", mesh);
  const manifest = {
    version: "1.0",
    units: "mm",
    anonymized_case_id: crypto.randomUUID(),
    healthy_side: side,
    midline: { point: [midlineX,0,0], normal: [1,0,0] },
    base_fit: { enabled: true, offset_mm: offset }
  };
  zip.file("manifest.json", JSON.stringify(manifest, null, 2));
  const blob = await zip.generateAsync({type:"blob"});

  const form = new FormData();
  form.append("zipfile_in", blob, "case.zip");
  const res = await fetch("http://localhost:8000/upload", { method: "POST", body: form });
  const json = await res.json();
  document.getElementById('out').textContent = JSON.stringify(json, null, 2);

  // simple poll for links
  const { case_id, job_id } = json;
  const links = async () => (await fetch(`http://localhost:8000/download/${case_id}`)).json();
  let tries = 0; let data;
  do {
    await new Promise(r=>setTimeout(r, 4000));
    data = await links();
    tries++;
    document.getElementById('out').textContent = "Waiting...\n" + JSON.stringify(data, null, 2);
  } while (tries < 30); // 2 minutes
}
document.getElementById('go').addEventListener('click', upload);
