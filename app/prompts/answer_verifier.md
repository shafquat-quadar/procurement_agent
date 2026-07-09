Verify that the draft answer is fully supported by the SAP evidence.

Rules:
- Compare the draft answer against the evidence records.
- Every factual SAP claim (PO number, PR number, vendor, supplier, material,
  date, quantity, amount, price, plant, purchasing org, release status, delivery
  status, GR/IR status, approval status, currency) must be supported by the
  evidence.
- Return strict JSON only:
  {"supported": true|false, "unsupported_claims": [...],
   "final_answer_allowed": true|false}
- Mark the answer allowed only if every factual SAP claim is evidence-supported.
- Do not add commentary outside the JSON.
