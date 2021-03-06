import gzip
import httpretty
import json
import os
import unittest
import urllib.request

from python3.shipper.shipper import MaxRetriesException, UnauthorizedAccessException, UnknownURL
from python3.shipper.shipper import LogzioShipper
from io import BytesIO


class TestLambdaFunction(unittest.TestCase):
    def setUp(self):
        # Set os.environ for tests
        os.environ['TOKEN'] = "12345678"
        os.environ['TYPE'] = "test_log"
        self._logzioUrl = "https://listener.logz.io:8071/?token={}".format(os.environ['TOKEN'])
        self._dec_data = []

    @staticmethod
    def generate_logs():
        logs = [
            {'k1': 'v1'},
            {'k2': 'v2'},
            {'k3': 'v3'},
            {'k4': 'v4'}
        ]
        return logs

    def ship_logs(self, logs):
        shipper = LogzioShipper()
        for log in logs:
            shipper.add(log)
        shipper.flush()
        return logs

    @staticmethod
    def delete_new_line(str_log):
        if str_log.endswith('\n'):
            return str_log[:-1]
        return str_log

    def read_body_logs(self, request):
        buf = BytesIO(request.body)
        try:
            body = gzip.GzipFile(mode='rb', fileobj=buf) if request.headers['Content-Encoding'] == 'gzip' else buf
        except KeyError:
            body = buf
        body_logs = body.readlines()
        return [self.delete_new_line(log.decode('utf-8')) for log in body_logs]

    def validate_data(self, request, logs):
        body_logs_list = self.read_body_logs(request)
        i = 0
        if len(body_logs_list) != len(logs):
            self.fail("Failed on extracting Gzip file")
        for log in logs:
            log = json.dumps(log)
            self.assertTrue(body_logs_list[i] == log)
            i = i + 1

    @httpretty.activate
    def test_ok_request(self):
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, body="first", status=200,
                               content_type="application/json")
        try:
            self.ship_logs(logs)
        except Exception:
            self.fail("Failed on handling a legit event. Expected status_code = 200")
        request = httpretty.HTTPretty.last_request
        self.validate_data(request, logs)

    @httpretty.activate
    def test_bad_request(self):
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, responses=[
                                httpretty.Response(body="first", status=400),
                                httpretty.Response(body="second", status=401),
                            ])

        self.ship_logs(logs)
        with self.assertRaises(UnauthorizedAccessException):
            self.ship_logs(logs)

    @httpretty.activate
    def test_ok_gzip_request(self):
        os.environ['COMPRESS'] = 'true'
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, body="first", status=200,
                               content_type="application/json")
        self.ship_logs(logs)
        request = httpretty.HTTPretty.last_request
        self.validate_data(request, logs)

    @httpretty.activate
    def test_gzip_typo_request(self):
        os.environ['COMPRESS'] = 'fakecompress'
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, body="first", status=200,
                               content_type="application/json")
        self.ship_logs(logs)
        request = httpretty.HTTPretty.last_request
        try:
            gzip_header = dict(request.headers)["Content-Encoding"]
            self.fail("Failed to send uncompressed logs with typo in compress env filed")
        except KeyError:
            pass

    @httpretty.activate
    def test_retry_request(self):
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, responses=[
                                httpretty.Response(body="1st Fail", status=500),
                                httpretty.Response(body="2nd Fail", status=500),
                                httpretty.Response(body="3rd Success", status=200)
                            ])
        try:
            self.ship_logs(logs)
        except Exception:
            self.fail("Should have succeeded on last try")

        request = httpretty.HTTPretty.last_request
        self.validate_data(request, logs)

    @httpretty.activate
    def test_retry_limit(self):
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, status=500)

        with self.assertRaises(MaxRetriesException):
            self.ship_logs(logs)

    @httpretty.activate
    def test_bad_url(self):
        logs = self.generate_logs()
        httpretty.register_uri(httpretty.POST, self._logzioUrl, status=404)

        with self.assertRaises(UnknownURL):
            self.ship_logs(logs)

if __name__ == '__main__':
    unittest.main()
