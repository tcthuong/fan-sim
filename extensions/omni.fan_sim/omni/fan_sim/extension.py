import json
import urllib.request

import omni.ext
import omni.ui as ui
import omni.usd


class FanSimExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        self._window = ui.Window("Fan-Sim", width=360, height=220)
        self._service_url = "http://127.0.0.1:8765"
        self._case_id = "fan_base"
        self._rpm = 1200.0
        self._outlet_pressure = 20.0
        with self._window.frame:
            with ui.VStack(spacing=6):
                ui.Label("Fan-Sim Inference")
                self._service_field = ui.StringField()
                self._service_field.model.set_value(self._service_url)
                self._case_field = ui.StringField()
                self._case_field.model.set_value(self._case_id)
                self._rpm_field = ui.FloatField()
                self._rpm_field.model.set_value(self._rpm)
                self._pout_field = ui.FloatField()
                self._pout_field.model.set_value(self._outlet_pressure)
                ui.Button("Predict And Load USD", clicked_fn=self._predict_and_load)
                self._status = ui.Label("")

    def on_shutdown(self):
        self._window = None

    def _predict_and_load(self):
        self._service_url = self._service_field.model.get_value_as_string()
        self._case_id = self._case_field.model.get_value_as_string()
        self._rpm = self._rpm_field.model.get_value_as_float()
        self._outlet_pressure = self._pout_field.model.get_value_as_float()
        payload = {
            "case_id": self._case_id,
            "rpm": self._rpm,
            "outlet_pressure": self._outlet_pressure,
            "outputs": ["vtu", "usd", "streamlines", "particles"],
        }
        try:
            request = urllib.request.Request(
                f"{self._service_url.rstrip('/')}/predict",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
            usd_path = body["prediction_usd"]
            omni.usd.get_context().open_stage(usd_path)
            self._status.text = f"Loaded {usd_path}"
        except Exception as exc:
            self._status.text = f"Fan-Sim error: {exc}"

