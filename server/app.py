import pandas as pd
from pandas.core.indexes.base import Index
from flask import Flask, jsonify, request, json, abort
from flask_cors import CORS
from MICPredictor import MICPredictor
from treatmentRanking import treatmentRanking
from contextAware import contextAware
import re


# configuration
DEBUG = True


class EndpointAction(object):
    """
    Endpoint class.
    when it called performers the action
    """

    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action()


class WebService(object):
    """
    Wrapper class for app
    creates and runs the app
    """

    def __init__(self, name):
        self.app = Flask(name)
        self.app.config.from_object(__name__)
        # enable CORS
        CORS(self.app, resources={r'/*': {'origins': '*'}})
        self.mic_predictor = MICPredictor()
        self.treatment_ranking = treatmentRanking()
        self.context_aware = contextAware()

    def run(self):
        self.app.run(debug=True)

    def add_endpoint(self, endpoint=None, endpoint_name=None, handler=None):
        """
        Links between specific endpoint url to a given handler function
        :param endpoint: url, str
        :param endpoint_name: name of operation, str
        :param handler: callable function, called on request
        :return: void, adds the endpoint to the app
        """
        self.app.add_url_rule(endpoint, endpoint_name, EndpointAction(
            handler), methods=['GET', 'POST'])

    def response(self, message, status):
        """

        :param message: message to send, str
        :param status: HTTP response code, int
        :return: response to client
        """
        response = self.app.response_class(
            response=json.dumps(message),
            status=status,
            mimetype='application/json'
        )
        return response

    def generate_recommendation(self):
        """
        the function validates that input is valid and then generates a treatment recommendation table based on input.
        :return: recommendation table as json
        """
        gene_correlation_csv = request.files['gene_correlation_csv']
        gene_correlation_txt = request.files['gene_correlation_txt']
        patient_id = request.form['id']
        patient_age = request.form['patientAge']
        patient_gender = request.form['patientGender']
        patient_creatinine = float(request.form['patientCreatinine'])
        patient_fever = json.loads(request.form['patientFever'])
        patient_plank_pain = json.loads(request.form['patientFlankPain'])
        patient_dysuria = json.loads(request.form['patientDysuria'])
        patient_drugs_in_use = request.form['patientDrugsInUse'].split(",")
        print(patient_drugs_in_use)
        try:
            if not self.check_valid_id(patient_id):
                return self.response("Invalid Id", 409)
            csv_file = self.read_csv_file(gene_correlation_csv)
            txt_file = self.read_txt_file(gene_correlation_txt)
            # print(txt_file)
            message = self.check_valid_csv(csv_file)
            if message != '':
                return self.response('Error in csv file! \n' + message, 400)
            message = self.check_valid_txt(txt_file)
            if message != '':
                return self.response('Error in txt file! \n' + message, 400)
            mic = self.mic_predictor.predict(csv_file, txt_file)
            initial_ranking = self.treatment_ranking.rank(mic)
            final_ranking = self.context_aware.rank(initial_ranking)
            return jsonify(final_ranking)
        except Exception as e:
            print(e)
            return self.response("Something went worng!", 400)

    def check_valid_id(self, patient_id):
        # check in future public patients DB that patient id exists.
        return True

    def check_valid_txt(self, gene_correlation_txt):
        """
        check if the given txt file is in the requested format.
        :param gene_correlation_txt: the system input - file of gene correlation, txt file
        :return: error message or empty message according to validation
        """
        message = ''
        float_regex = '[0-9]+\.[0-9]+'
        for i, row in enumerate(gene_correlation_txt):
            # remove '\n' and convert from bytes to string
            row = row[:-1].decode("utf-8")
            row_tokens = row.split(" ")
            if not row_tokens[0].startswith(">contig"):
                message = f'line {i+1} , column 1 starts with invalid value'
                break
            if not row_tokens[1].startswith("len=") or not row_tokens[1][4:].isdecimal():
                message = f'line {i+1}, column 2 has invalid value'
                break
            if not row_tokens[2].startswith("cov=") or not re.search(float_regex, row_tokens[2][4:]):
                message = f'line {i+1}, column 3 has invalid value'
                break
        return message

    def check_valid_csv(self, gene_correlation_csv):
        """
        check if the given csv file is in the requested format.
        :param gene_correlation_csv: the system input - file of gene correlation, csv file
        :return: error message or empty message according to validation
        """
        message = ''
        required_columns = {"file": str, "gene": str, "contig": str, "start": int,
                            "end": int, "depth": float, "seqid": float, "seqcov": float,
                            "match_start": int, "match_end": int, "ref_gene_size": int}

        # rename columns name to lower case
        gene_correlation_csv.columns = gene_correlation_csv.columns.str.lower()
        # check if all the required columns exists
        for col_name in required_columns.keys():
            if col_name not in gene_correlation_csv.columns:
                message = f'column "{col_name}" is missing'
                return message
        if len(required_columns.keys()) != len(gene_correlation_csv.columns):
            message = f'expected {len(required_columns.keys())} columns but got {len(gene_correlation_csv.columns)}'
        # check if the 'file' column have 1 value
        elif len(gene_correlation_csv["file"].unique()) != 1:
            message = f'expected 1 unique value in column "file" but got {len(gene_correlation_csv["file"].unique())}'
        # check there is no missing values in 'gene' column
        elif gene_correlation_csv["gene"].isnull().any():
            message = "column 'gene' can't have missing values."
        # check contig column values are in right format.
        else:
            for i, val in enumerate(gene_correlation_csv["contig"]):
                if not val.lower().startswith("contig") or not val[6:].isdigit():
                    message = f'Invalid value in column "contig" row {i+2}'
                    return message
            # check if all values in int/float columns are int/float and in the neccesary range.
            for col_name, col_type in required_columns.items():
                if col_type == int:
                    if not all(isinstance(val, int) for val in gene_correlation_csv[col_name]):
                        message = f'column {col_name} have invalid value - Not all values are decimal numbers'
                elif col_type == float:
                    if not all(isinstance(val, float) or isinstance(val, int) for val in gene_correlation_csv[col_name]):
                        message = f'column {col_name} have invalid value - Not all values are real numbers'
                if col_name == "seqid" or col_name == "seqcov":
                    if not all(0 <= val <= 100 for val in gene_correlation_csv[col_name]):
                        message = f'column {col_name} have invalid value'
        return message

    def read_txt_file(self, file):
        return file.readlines()

    def read_csv_file(self, file):
        return pd.read_csv(file, index_col=0)


# open the server class. add endpoint and start running the server.
web_service_app = WebService('webservice')
web_service_app.add_endpoint(endpoint='/generate', endpoint_name='generate recommendation',
                             handler=web_service_app.generate_recommendation)
web_service_app.run()
