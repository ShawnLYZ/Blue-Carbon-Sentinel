import bcs_gs
import bcs_protocol


def test_packages_import_and_report_version():
    assert bcs_gs.__version__ == "0.1.0"
    assert bcs_protocol.__version__ == "0.1.0"
