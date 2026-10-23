from scripts.inspect_csv import inspect


def test_header_detection_not_filename(tmp_path):
    path = tmp_path / 'df_Fid_Uid_link_hack.csv'
    path.write_text('PAYER,BENEFICIARY,PAY_AMT,PAY_CNT\nA,B,100,2\n', encoding='utf-8')
    result = inspect(path)
    assert result['detected_types'] == ['payments']
    assert result['rows'] == 1
