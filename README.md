# limin-design.github.io

Source of [limin-design.github.io](https://limin-design.github.io): my projects with live demos.

- `index.html`: project page.
- `invoice-demo/`: the store pricing app's interface and its own invoice reader (`invoice-demo/py/loja`). Photograph a real Portuguese invoice: ZXing reads the fiscal QR code, PaddleOCR (PP-OCRv4, the OCR models the store uses, bundled from [Guten OCR](https://github.com/gutenye/ocr) in `invoice-demo/vendor`) reads the text, and the reader runs in the browser with [Pyodide](https://pyodide.org) to tie each product code to its quantity × price = value and prove the invoice against the QR. Nothing leaves the device. The Exemplos tab runs the [invoice-pricing-demo](https://github.com/Limin-design/invoice-pricing-demo) package on a synthetic store.
- `stratforge/`: static build of the [StratForge](https://github.com/Limin-design/stratforge) web app.
