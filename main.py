from flask import Flask, render_template, redirect, url_for, request, session
from flask_bootstrap import Bootstrap
from flask_pymongo import PyMongo
from flask_wtf import FlaskForm
from wtforms import RadioField, FloatField, IntegerField, StringField, PasswordField, FileField
from wtforms.fields import DateField
from wtforms.validators import NumberRange, InputRequired, Email, Length, EqualTo
from werkzeug.utils import secure_filename
import random
import string
import os
import pandas as pd
import numpy as np
import scipy as sp
import datetime
import matplotlib.pyplot as plt
import mpld3
from bokeh.plotting import figure, show
from bokeh.models import DatetimeTickFormatter
from bokeh.embed import components
from calendar import monthrange

app = Flask(__name__)
# app.config['MONGO_URI'] = "mongodb://redwan1006066:14243444redwan@ds044989.mlab.com:44989/tanksize2?retryWrites=false"
app.config['MONGO_URI'] = "mongodb://localhost:27017/tanksize"
app.config['SECRET_KEY'] = 'yothisissecret'
app.config['UPLOAD_FOLDER'] = 'data'
Bootstrap(app)
mongo = PyMongo(app)

pd.set_option('mode.chained_assignment', None)


def get_random_string(length):
    letters = string.ascii_lowercase
    result_str = ''.join(random.choice(letters) for i in range(length))
    return result_str


def conv_int(a):
    try:
        int(a)
        return int(a)
    except ValueError:
        return 0


def conv_float(a):
    try:
        float(a)
        return float(a)
    except ValueError:
        return 0.0


def conv_met_2_imp(uname):
    # multiply area by 10.76
    # divide volume by 3.78
    userquery = {"username": uname}
    areakeys = ['RoofMembraneArea', 'RoofAsphaultShingleArea', 'RoofMetalArea', 'RoofGreenRoofArea',
                'RoofTerracottaArea',
                'RoofOtherArea', 'NonRoofImperviousAsphaultArea', 'NonRoofImperviousBrickArea',
                'NonRoofImperviousOtherArea',
                'SemiperviousGrassTurfSandyFlatArea', 'SemiperviousGrassTurfSandyAvArea',
                'SemiperviousGrassTurfSandySteepArea',
                'SemiperviousGrassTurfClayFlatArea', 'SemiperviousGrassTurfClayAvArea',
                'SemiperviousGrassTurfClaySteepArea',
                'SemiperviousGravelArea', 'SemiperviousLandScapeArea', 'SemiperviousForestedArea', 'OtherArea']

    volkeys = ['IceMakingJan', 'IceMakingFeb', 'IceMakingMar',
               'IceMakingApr', 'IceMakingMay', 'IceMakingJun',
               'IceMakingJul', 'IceMakingAug', 'IceMakingSep',
               'IceMakingOct', 'IceMakingNov', 'IceMakingDec',
               'CoolingTowerJan', 'CoolingTowerFeb', 'CoolingTowerMar',
               'CoolingTowerApr', 'CoolingTowerMay', 'CoolingTowerJun',
               'CoolingTowerJul', 'CoolingTowerAug', 'CoolingTowerSep',
               'CoolingTowerOct', 'CoolingTowerNov', 'CoolingTowerDec',
               'IceSkatingJan', 'IceSkatingFeb', 'IceSkatingMar',
               'IceSkatingApr', 'IceSkatingMay', 'IceSkatingJun',
               'IceSkatingJul', 'IceSkatingAug', 'IceSkatingSep',
               'IceSkatingOct', 'IceSkatingNov', 'IceSkatingDec',
               'OtherIndoorJan', 'OtherIndoorFeb', 'OtherIndoorMar',
               'OtherIndoorApr', 'OtherIndoorMay', 'OtherIndoorJun',
               'OtherIndoorJul', 'OtherIndoorAug', 'OtherIndoorSep',
               'OtherIndoorOct', 'OtherIndoorNov', 'OtherIndoorDec',
               'SprayIrrigationJan', 'SprayIrrigationFeb', 'SprayIrrigationMar',
               'SprayIrrigationApr', 'SprayIrrigationMay', 'SprayIrrigationJun',
               'SprayIrrigationJul', 'SprayIrrigationAug', 'SprayIrrigationSep',
               'SprayIrrigationOct', 'SprayIrrigationNov', 'SprayIrrigationDec',
               'DripIrrigationJan', 'DripIrrigationFeb', 'DripIrrigationMar',
               'DripIrrigationApr', 'DripIrrigationMay', 'DripIrrigationJun',
               'DripIrrigationJul', 'DripIrrigationAug', 'DripIrrigationSep',
               'DripIrrigationOct', 'DripIrrigationNov', 'DripIrrigationDec',
               'VehicularWashingJan', 'VehicularWashingFeb', 'VehicularWashingMar',
               'VehicularWashingApr', 'VehicularWashingMay', 'VehicularWashingJun',
               'VehicularWashingJul', 'VehicularWashingAug', 'VehicularWashingSep',
               'VehicularWashingOct', 'VehicularWashingNov', 'VehicularWashingDec',
               'OtherOutdoorJan', 'OtherOutdoorFeb', 'OtherOutdoorMar',
               'OtherOutdoorApr', 'OtherOutdoorMay', 'OtherOutdoorJun',
               'OtherOutdoorJul', 'OtherOutdoorAug', 'OtherOutdoorSep',
               'OtherOutdoorOct', 'OtherOutdoorNov', 'OtherOutdoorDec']

    areadata = [mongo.db.tankdata.find_one(userquery)[i] for i in areakeys]
    voldata = [mongo.db.tankdata.find_one(userquery)[i] for i in volkeys]

    areadata = [i * 10.76 for i in areadata]
    voldata = [i / 3.78 for i in voldata]

    for i in range(0, len(areakeys)):
        mongo.db.tankdata.update_one(userquery, {"$set": {areakeys[i]: areadata[i]}})

    for i in range(0, len(volkeys)):
        mongo.db.tankdata.update_one(userquery, {"$set": {volkeys[i]: voldata[i]}})

    print("conv_met_2_imp")

    return


def conv_imp_2_met(uname):
    userquery = {"username": uname}
    areakeys = ['RoofMembraneArea', 'RoofAsphaultShingleArea', 'RoofMetalArea', 'RoofGreenRoofArea',
                'RoofTerracottaArea',
                'RoofOtherArea', 'NonRoofImperviousAsphaultArea', 'NonRoofImperviousBrickArea',
                'NonRoofImperviousOtherArea',
                'SemiperviousGrassTurfSandyFlatArea', 'SemiperviousGrassTurfSandyAvArea',
                'SemiperviousGrassTurfSandySteepArea',
                'SemiperviousGrassTurfClayFlatArea', 'SemiperviousGrassTurfClayAvArea',
                'SemiperviousGrassTurfClaySteepArea',
                'SemiperviousGravelArea', 'SemiperviousLandScapeArea', 'SemiperviousForestedArea', 'OtherArea']

    volkeys = ['IceMakingJan', 'IceMakingFeb', 'IceMakingMar',
               'IceMakingApr', 'IceMakingMay', 'IceMakingJun',
               'IceMakingJul', 'IceMakingAug', 'IceMakingSep',
               'IceMakingOct', 'IceMakingNov', 'IceMakingDec',
               'CoolingTowerJan', 'CoolingTowerFeb', 'CoolingTowerMar',
               'CoolingTowerApr', 'CoolingTowerMay', 'CoolingTowerJun',
               'CoolingTowerJul', 'CoolingTowerAug', 'CoolingTowerSep',
               'CoolingTowerOct', 'CoolingTowerNov', 'CoolingTowerDec',
               'IceSkatingJan', 'IceSkatingFeb', 'IceSkatingMar',
               'IceSkatingApr', 'IceSkatingMay', 'IceSkatingJun',
               'IceSkatingJul', 'IceSkatingAug', 'IceSkatingSep',
               'IceSkatingOct', 'IceSkatingNov', 'IceSkatingDec',
               'OtherIndoorJan', 'OtherIndoorFeb', 'OtherIndoorMar',
               'OtherIndoorApr', 'OtherIndoorMay', 'OtherIndoorJun',
               'OtherIndoorJul', 'OtherIndoorAug', 'OtherIndoorSep',
               'OtherIndoorOct', 'OtherIndoorNov', 'OtherIndoorDec',
               'SprayIrrigationJan', 'SprayIrrigationFeb', 'SprayIrrigationMar',
               'SprayIrrigationApr', 'SprayIrrigationMay', 'SprayIrrigationJun',
               'SprayIrrigationJul', 'SprayIrrigationAug', 'SprayIrrigationSep',
               'SprayIrrigationOct', 'SprayIrrigationNov', 'SprayIrrigationDec',
               'DripIrrigationJan', 'DripIrrigationFeb', 'DripIrrigationMar',
               'DripIrrigationApr', 'DripIrrigationMay', 'DripIrrigationJun',
               'DripIrrigationJul', 'DripIrrigationAug', 'DripIrrigationSep',
               'DripIrrigationOct', 'DripIrrigationNov', 'DripIrrigationDec',
               'VehicularWashingJan', 'VehicularWashingFeb', 'VehicularWashingMar',
               'VehicularWashingApr', 'VehicularWashingMay', 'VehicularWashingJun',
               'VehicularWashingJul', 'VehicularWashingAug', 'VehicularWashingSep',
               'VehicularWashingOct', 'VehicularWashingNov', 'VehicularWashingDec',
               'OtherOutdoorJan', 'OtherOutdoorFeb', 'OtherOutdoorMar',
               'OtherOutdoorApr', 'OtherOutdoorMay', 'OtherOutdoorJun',
               'OtherOutdoorJul', 'OtherOutdoorAug', 'OtherOutdoorSep',
               'OtherOutdoorOct', 'OtherOutdoorNov', 'OtherOutdoorDec']

    areadata = [mongo.db.tankdata.find_one(userquery)[i] for i in areakeys]
    voldata = [mongo.db.tankdata.find_one(userquery)[i] for i in volkeys]

    areadata = [i / 10.76 for i in areadata]
    voldata = [i * 3.78 for i in voldata]

    for i in range(0, len(areakeys)):
        mongo.db.tankdata.update_one(userquery, {"$set": {areakeys[i]: areadata[i]}})

    for i in range(0, len(volkeys)):
        mongo.db.tankdata.update_one(userquery, {"$set": {volkeys[i]: voldata[i]}})

    print("conv_imp_2_met")
    return


class LoginForm(FlaskForm):
    email = StringField('Enter your Email', validators=[InputRequired(), Email()])
    password = PasswordField('Enter your password', validators=[InputRequired(), Length(min=8, max=16,
                                                                                        message='password should be between 8 to 16 characters')])


class RegistrationForm(FlaskForm):
    email = StringField('Enter your Email', validators=[InputRequired(), Email()])
    password = PasswordField('Enter your password', validators=[InputRequired(),
                                                                Length(min=8, max=16,
                                                                       message='password should be between 8 to 16 characters'),
                                                                EqualTo('conf_password',
                                                                        message='Passwords do not match')])
    conf_password = PasswordField('Confirm your password', validators=[InputRequired(), Length(min=8, max=16,
                                                                                               message='password should be between 8 to 16 characters')])

    address = StringField('Street Address')
    title = StringField('Enter Title', validators=[InputRequired()])
    company = StringField('Enter your company', validators=[InputRequired()])


class Unitform(FlaskForm):
    example = RadioField('UnitSystem', choices=[('Metric', 'Metric'), ('Imperial', 'Imperial')])


class RoofArea(FlaskForm):
    RoofMembraneArea = FloatField('Enter Area')
    RoofMembraneRunoffCoeff = FloatField('Enter Run-off Coefficient')
    RoofAsphaultShingleArea = FloatField('Enter Area')
    RoofAsphaultShingleRunoffCoeff = FloatField('Enter Run-off Coefficient')
    RoofMetalArea = FloatField('Enter Area')
    RoofMetalRunoffCoeff = FloatField('Enter Run-off Coefficient')
    RoofGreenRoofArea = FloatField('Enter Area')
    RoofGreenRoofRunoffCoeff = FloatField('Enter Run-off Coefficient')
    RoofTerracottaArea = FloatField('Enter Area')
    RoofTerracottaRunoffCoeff = FloatField('Enter Run-off Coefficient')
    RoofOtherArea = FloatField('Enter Area')
    RoofOtherRunoffCoeff = FloatField('Enter Run-off Coefficient')


class NonRoofArea(FlaskForm):
    NonRoofImperviousAsphaultArea = FloatField('Enter Area')
    NonRoofImperviousAsphaultRunoffCoeff = FloatField('Enter Run-off Coefficient')
    NonRoofImperviousBrickArea = FloatField('Enter Area')
    NonRoofImperviousBrickRunoffCoeff = FloatField('Enter Run-off Coefficient')
    NonRoofImperviousOtherArea = FloatField('Enter Area')
    NonRoofImperviousOtherRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfArea = FloatField('Enter Area')
    SemiperviousGrassTurfRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfSandyFlatArea = FloatField('Enter Area')
    SemiperviousGrassTurfSandyFlatRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfSandyAvArea = FloatField('Enter Area')
    SemiperviousGrassTurfSandyAvRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfSandySteepArea = FloatField('Enter Area')
    SemiperviousGrassTurfSandySteepRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfClayFlatArea = FloatField('Enter Area')
    SemiperviousGrassTurfClayFlatRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfClayAvArea = FloatField('Enter Area')
    SemiperviousGrassTurfClayAvRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfClaySteepArea = FloatField('Enter Area')
    SemiperviousGrassTurfRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGrassTurfClaySteepRunoffCoeff = FloatField('Enter Area')
    SemiperviousShrubberyRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousForestedArea = FloatField('Enter Area')
    SemiperviousForestedRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousGravelArea = FloatField('Enter Area')
    SemiperviousGravelRunoffCoeff = FloatField('Enter Run-off Coefficient')
    SemiperviousLandScapeArea = FloatField('Enter Area')
    SemiperviousLandScapeRunoffCoeff = FloatField('Enter Run-off Coefficient')
    EngineeredSemiperviousArea = FloatField('Enter Area')
    EngineeredSemiperviousRunoffCoeff = FloatField('Enter Run-off Coefficient')
    OtherArea = FloatField('Enter Area')
    OtherRunoffCoeff = FloatField('Enter Run-off Coefficient')


class IndoorDemand(FlaskForm):
    AvFlushperPerson = FloatField('Enter Average Number of flushes per person')
    AvGalperFlushToilets = FloatField('Enter Average Number of gallons per flush for Toilets')
    AvGalperFlushUrinals = FloatField('Enter Average Number of gallons per flush for Urinals')

    OccupJan = FloatField('Januray')
    OccupFeb = FloatField('February')
    OccupMar = FloatField('March')
    OccupApr = FloatField('April')
    OccupMay = FloatField('May')
    OccupJun = FloatField('June')
    OccupJul = FloatField('July')
    OccupAug = FloatField('August')
    OccupSep = FloatField('September')
    OccupOct = FloatField('October')
    OccupNov = FloatField('November')
    OccupDec = FloatField('December')

    UrinalJan = FloatField('Januray')
    UrinalFeb = FloatField('February')
    UrinalMar = FloatField('March')
    UrinalApr = FloatField('April')
    UrinalMay = FloatField('May')
    UrinalJun = FloatField('June')
    UrinalJul = FloatField('July')
    UrinalAug = FloatField('August')
    UrinalSep = FloatField('September')
    UrinalOct = FloatField('October')
    UrinalNov = FloatField('November')
    UrinalDec = FloatField('December')

    IceMakingJan = FloatField('Januray')
    IceMakingFeb = FloatField('February')
    IceMakingMar = FloatField('March')
    IceMakingApr = FloatField('April')
    IceMakingMay = FloatField('May')
    IceMakingJun = FloatField('June')
    IceMakingJul = FloatField('July')
    IceMakingAug = FloatField('August')
    IceMakingSep = FloatField('September')
    IceMakingOct = FloatField('October')
    IceMakingNov = FloatField('November')
    IceMakingDec = FloatField('December')

    CoolingTowerJan = FloatField('Januray')
    CoolingTowerFeb = FloatField('February')
    CoolingTowerMar = FloatField('March')
    CoolingTowerApr = FloatField('April')
    CoolingTowerMay = FloatField('May')
    CoolingTowerJun = FloatField('June')
    CoolingTowerJul = FloatField('July')
    CoolingTowerAug = FloatField('August')
    CoolingTowerSep = FloatField('September')
    CoolingTowerOct = FloatField('October')
    CoolingTowerNov = FloatField('November')
    CoolingTowerDec = FloatField('December')

    IceSkatingJan = FloatField('Januray')
    IceSkatingFeb = FloatField('February')
    IceSkatingMar = FloatField('March')
    IceSkatingApr = FloatField('April')
    IceSkatingMay = FloatField('May')
    IceSkatingJun = FloatField('June')
    IceSkatingJul = FloatField('July')
    IceSkatingAug = FloatField('August')
    IceSkatingSep = FloatField('September')
    IceSkatingOct = FloatField('October')
    IceSkatingNov = FloatField('November')
    IceSkatingDec = FloatField('December')

    OtherIndoorJan = FloatField('Januray')
    OtherIndoorFeb = FloatField('February')
    OtherIndoorMar = FloatField('March')
    OtherIndoorApr = FloatField('April')
    OtherIndoorMay = FloatField('May')
    OtherIndoorJun = FloatField('June')
    OtherIndoorJul = FloatField('July')
    OtherIndoorAug = FloatField('August')
    OtherIndoorSep = FloatField('September')
    OtherIndoorOct = FloatField('October')
    OtherIndoorNov = FloatField('November')
    OtherIndoorDec = FloatField('December')


class IndoorDemand2(FlaskForm):
    AvFlushperPerson = FloatField('Enter Average Number of flushes per person')
    AvGalperFlushToilets = FloatField('Enter Average Number of gallons per flush for Toilets')
    AvGalperFlushUrinals = FloatField('Enter Average Number of gallons per flush for Urinals')

    Occup = FloatField('Enter Average number of male per day')
    Urinal = FloatField('Enter Average number of female per day')
    IceMaking = FloatField('Enter Average Ice Making Demand per month')
    CoolingTower = FloatField('Enter Average Cooling Tower Demand per month')
    IceSkating = FloatField('Enter Average Ice Skating Demand per month')
    OtherIndoor = FloatField('Enter Other Indoor Demand per month')


class OutdoorDemand(FlaskForm):
    SprayIrrigationJan = FloatField('Januray')
    SprayIrrigationFeb = FloatField('February')
    SprayIrrigationMar = FloatField('March')
    SprayIrrigationApr = FloatField('April')
    SprayIrrigationMay = FloatField('May')
    SprayIrrigationJun = FloatField('June')
    SprayIrrigationJul = FloatField('July')
    SprayIrrigationAug = FloatField('August')
    SprayIrrigationSep = FloatField('September')
    SprayIrrigationOct = FloatField('October')
    SprayIrrigationNov = FloatField('November')
    SprayIrrigationDec = FloatField('December')

    DripIrrigationJan = FloatField('Januray')
    DripIrrigationFeb = FloatField('February')
    DripIrrigationMar = FloatField('March')
    DripIrrigationApr = FloatField('April')
    DripIrrigationMay = FloatField('May')
    DripIrrigationJun = FloatField('June')
    DripIrrigationJul = FloatField('July')
    DripIrrigationAug = FloatField('August')
    DripIrrigationSep = FloatField('September')
    DripIrrigationOct = FloatField('October')
    DripIrrigationNov = FloatField('November')
    DripIrrigationDec = FloatField('December')

    VehicularWashingJan = FloatField('Januray')
    VehicularWashingFeb = FloatField('February')
    VehicularWashingMar = FloatField('March')
    VehicularWashingApr = FloatField('April')
    VehicularWashingMay = FloatField('May')
    VehicularWashingJun = FloatField('June')
    VehicularWashingJul = FloatField('July')
    VehicularWashingAug = FloatField('August')
    VehicularWashingSep = FloatField('September')
    VehicularWashingOct = FloatField('October')
    VehicularWashingNov = FloatField('November')
    VehicularWashingDec = FloatField('December')

    OtherOutdoorJan = FloatField('Januray')
    OtherOutdoorFeb = FloatField('February')
    OtherOutdoorMar = FloatField('March')
    OtherOutdoorApr = FloatField('April')
    OtherOutdoorMay = FloatField('May')
    OtherOutdoorJun = FloatField('June')
    OtherOutdoorJul = FloatField('July')
    OtherOutdoorAug = FloatField('August')
    OtherOutdoorSep = FloatField('September')
    OtherOutdoorOct = FloatField('October')
    OtherOutdoorNov = FloatField('November')
    OtherOutdoorDec = FloatField('December')


class OutdoorDemand2(FlaskForm):
    SprayIrrigation = FloatField('Enter Spray Irrigation Demand Per Month')
    DripIrrigation = FloatField('Enter Drip Irrigation Demand Per Month')
    VehicularWashing = FloatField('Enter Vehicular Washing Demand Per Month')
    OtherOutdoor = FloatField('Enter Other Outdoor Demand Per Month')


class Raindata(FlaskForm):
    input_file = FileField('Enter Rain-Fall Data')


class GraphQuery(FlaskForm):
    start_point = FloatField('Enter the smallest tank size')
    end_point = FloatField('Enter the largest tank size ')
    step = FloatField('Enter increment of tank size for graph')
    init_fill = FloatField('Enter initial fill percentage of tank')
    rel_percent = FloatField('Enter percentage of tank that should be filled for reliable water supply')


class WaterPlotQuery(FlaskForm):
    tanksize = FloatField('Enter your tank size in gallons')
    init_fill = FloatField('Enter initial fill percentage of tank')
    rel_percent = FloatField('Enter percentage of tank that should be filled for reliable water supply')


@app.route('/unit_choice', methods=['GET', 'POST'])
def unit_choice():
    form = Unitform()
    uname = session.get('uid')
    print(uname)
    if uname is None:
        return redirect(url_for('login_data'))
    # mongo.db.testdb.update_one({"username": "user1"}, {"$set": {"password": "pass2"}})
    if form.is_submitted() and form.example.data is not None:
        print(form.example.data)
        cur_unit = mongo.db.tankdata.find_one({"username": uname})['UnitChoice']
        if cur_unit != form.example.data:
            if cur_unit == "Metric" and form.example.data == "Imperial":
                conv_met_2_imp(uname)
                mongo.db.tankdata.update_one({"username": uname}, {"$set": {"UnitChoice": form.example.data}})
            elif cur_unit == "Imperial" and form.example.data == "Metric":
                conv_imp_2_met(uname)
                mongo.db.tankdata.update_one({"username": uname}, {"$set": {"UnitChoice": form.example.data}})
            else:
                mongo.db.tankdata.update_one({"username": uname}, {"$set": {"UnitChoice": form.example.data}})

        return redirect(url_for('user_index'))

    return render_template('unitchoice.html', form=form)


@app.route('/collection_area_data')
def collectareadat():
    return render_template('CollAreaDet.html')


@app.route('/demand_data')
def demanddat():
    return render_template('DemandDet.html')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/user_view')
def user_index():
    return render_template('user_index.html')


@app.route('/report_view', methods=['GET', 'POST'])
def rep_page():
    form1 = RoofArea()
    form2 = NonRoofArea()
    form3 = IndoorDemand()
    form4 = OutdoorDemand()
    form5 = GraphQuery()


    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    form1.RoofMembraneArea.data = mongo.db.tankdata.find_one(userquery)['RoofMembraneArea']
    form1.RoofMembraneRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofMembraneRunoffCoeff']
    form1.RoofAsphaultShingleArea.data = mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleArea']
    form1.RoofAsphaultShingleRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleRunoffCoeff']
    form1.RoofMetalArea.data = mongo.db.tankdata.find_one(userquery)['RoofMetalArea']
    form1.RoofMetalRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofMetalRunoffCoeff']
    form1.RoofGreenRoofArea.data = mongo.db.tankdata.find_one(userquery)['RoofGreenRoofArea']
    form1.RoofGreenRoofRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofGreenRoofRunoffCoeff']
    form1.RoofTerracottaArea.data = mongo.db.tankdata.find_one(userquery)['RoofTerracottaArea']
    form1.RoofTerracottaRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofTerracottaRunoffCoeff']
    form1.RoofOtherArea.data = mongo.db.tankdata.find_one(userquery)['RoofOtherArea']
    form1.RoofOtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofOtherRunoffCoeff']

    form2.NonRoofImperviousAsphaultArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousAsphaultArea']
    form2.NonRoofImperviousAsphaultRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousAsphaultRunoffCoeff']
    form2.NonRoofImperviousBrickArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousBrickArea']
    form2.NonRoofImperviousBrickRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousBrickRunoffCoeff']
    form2.NonRoofImperviousOtherArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousOtherArea']
    form2.NonRoofImperviousOtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousOtherRunoffCoeff']

    form2.SemiperviousGrassTurfSandyFlatArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyFlatArea']
    form2.SemiperviousGrassTurfSandyFlatRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyFlatRunoffCoeff']

    form2.SemiperviousGrassTurfSandyAvArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyAvArea']
    form2.SemiperviousGrassTurfSandyAvRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyAvRunoffCoeff']

    form2.SemiperviousGrassTurfSandySteepArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandySteepArea']
    form2.SemiperviousGrassTurfSandySteepRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandySteepRunoffCoeff']
    form2.SemiperviousGrassTurfClayFlatArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayFlatArea']
    form2.SemiperviousGrassTurfClayFlatRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayFlatRunoffCoeff']
    form2.SemiperviousGrassTurfClayAvArea.data = mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayAvArea']
    form2.SemiperviousGrassTurfClayAvRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayAvRunoffCoeff']
    form2.SemiperviousGrassTurfClaySteepArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClaySteepArea']
    form2.SemiperviousGrassTurfClaySteepRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClaySteepRunoffCoeff']

    form2.SemiperviousGravelArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGravelArea']
    form2.SemiperviousGravelRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGravelRunoffCoeff']

    form2.SemiperviousLandScapeArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousLandScapeArea']
    form2.SemiperviousLandScapeRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousLandScapeRunoffCoeff']

    form2.SemiperviousForestedArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousForestedArea']
    form2.SemiperviousForestedRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousForestedRunoffCoeff']

    form2.EngineeredSemiperviousArea.data = mongo.db.tankdata.find_one(userquery)[
        'EngineeredSemiperviousArea']
    form2.EngineeredSemiperviousRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'EngineeredSemiperviousRunoffCoeff']
    form2.OtherArea.data = mongo.db.tankdata.find_one(userquery)['OtherArea']
    form2.OtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['OtherRunoffCoeff']

    form3.AvFlushperPerson.data = mongo.db.tankdata.find_one(userquery)['AvFlushperPerson']
    form3.AvGalperFlushToilets.data = mongo.db.tankdata.find_one(userquery)['AvGalperFlushToilets']
    form3.AvGalperFlushUrinals.data = mongo.db.tankdata.find_one(userquery)['AvGalperFlushUrinals']

    form3.OccupJan.data = mongo.db.tankdata.find_one(userquery)['OccupJan']
    form3.OccupFeb.data = mongo.db.tankdata.find_one(userquery)['OccupFeb']
    form3.OccupMar.data = mongo.db.tankdata.find_one(userquery)['OccupMar']
    form3.OccupApr.data = mongo.db.tankdata.find_one(userquery)['OccupApr']
    form3.OccupMay.data = mongo.db.tankdata.find_one(userquery)['OccupMay']
    form3.OccupJun.data = mongo.db.tankdata.find_one(userquery)['OccupJun']
    form3.OccupJul.data = mongo.db.tankdata.find_one(userquery)['OccupJul']
    form3.OccupAug.data = mongo.db.tankdata.find_one(userquery)['OccupAug']
    form3.OccupSep.data = mongo.db.tankdata.find_one(userquery)['OccupSep']
    form3.OccupOct.data = mongo.db.tankdata.find_one(userquery)['OccupOct']
    form3.OccupNov.data = mongo.db.tankdata.find_one(userquery)['OccupNov']
    form3.OccupDec.data = mongo.db.tankdata.find_one(userquery)['OccupDec']

    form3.UrinalJan.data = mongo.db.tankdata.find_one(userquery)['UrinalJan']
    form3.UrinalFeb.data = mongo.db.tankdata.find_one(userquery)['UrinalFeb']
    form3.UrinalMar.data = mongo.db.tankdata.find_one(userquery)['UrinalMar']
    form3.UrinalApr.data = mongo.db.tankdata.find_one(userquery)['UrinalApr']
    form3.UrinalMay.data = mongo.db.tankdata.find_one(userquery)['UrinalMay']
    form3.UrinalJun.data = mongo.db.tankdata.find_one(userquery)['UrinalJun']
    form3.UrinalJul.data = mongo.db.tankdata.find_one(userquery)['UrinalJul']
    form3.UrinalAug.data = mongo.db.tankdata.find_one(userquery)['UrinalAug']
    form3.UrinalSep.data = mongo.db.tankdata.find_one(userquery)['UrinalSep']
    form3.UrinalOct.data = mongo.db.tankdata.find_one(userquery)['UrinalOct']
    form3.UrinalNov.data = mongo.db.tankdata.find_one(userquery)['UrinalNov']
    form3.UrinalDec.data = mongo.db.tankdata.find_one(userquery)['UrinalDec']

    form3.IceMakingJan.data = mongo.db.tankdata.find_one(userquery)['IceMakingJan']
    form3.IceMakingFeb.data = mongo.db.tankdata.find_one(userquery)['IceMakingFeb']
    form3.IceMakingMar.data = mongo.db.tankdata.find_one(userquery)['IceMakingMar']
    form3.IceMakingApr.data = mongo.db.tankdata.find_one(userquery)['IceMakingApr']
    form3.IceMakingMay.data = mongo.db.tankdata.find_one(userquery)['IceMakingMay']
    form3.IceMakingJun.data = mongo.db.tankdata.find_one(userquery)['IceMakingJun']
    form3.IceMakingJul.data = mongo.db.tankdata.find_one(userquery)['IceMakingJul']
    form3.IceMakingAug.data = mongo.db.tankdata.find_one(userquery)['IceMakingAug']
    form3.IceMakingSep.data = mongo.db.tankdata.find_one(userquery)['IceMakingSep']
    form3.IceMakingOct.data = mongo.db.tankdata.find_one(userquery)['IceMakingOct']
    form3.IceMakingNov.data = mongo.db.tankdata.find_one(userquery)['IceMakingNov']
    form3.IceMakingDec.data = mongo.db.tankdata.find_one(userquery)['IceMakingDec']

    form3.CoolingTowerJan.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJan']
    form3.CoolingTowerFeb.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerFeb']
    form3.CoolingTowerMar.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerMar']
    form3.CoolingTowerApr.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerApr']
    form3.CoolingTowerMay.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerMay']
    form3.CoolingTowerJun.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJun']
    form3.CoolingTowerJul.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJul']
    form3.CoolingTowerAug.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerAug']
    form3.CoolingTowerSep.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerSep']
    form3.CoolingTowerOct.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerOct']
    form3.CoolingTowerNov.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerNov']
    form3.CoolingTowerDec.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerDec']

    form3.IceSkatingJan.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJan']
    form3.IceSkatingFeb.data = mongo.db.tankdata.find_one(userquery)['IceSkatingFeb']
    form3.IceSkatingMar.data = mongo.db.tankdata.find_one(userquery)['IceSkatingMar']
    form3.IceSkatingApr.data = mongo.db.tankdata.find_one(userquery)['IceSkatingApr']
    form3.IceSkatingMay.data = mongo.db.tankdata.find_one(userquery)['IceSkatingMay']
    form3.IceSkatingJun.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJun']
    form3.IceSkatingJul.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJul']
    form3.IceSkatingAug.data = mongo.db.tankdata.find_one(userquery)['IceSkatingAug']
    form3.IceSkatingSep.data = mongo.db.tankdata.find_one(userquery)['IceSkatingSep']
    form3.IceSkatingOct.data = mongo.db.tankdata.find_one(userquery)['IceSkatingOct']
    form3.IceSkatingNov.data = mongo.db.tankdata.find_one(userquery)['IceSkatingNov']
    form3.IceSkatingDec.data = mongo.db.tankdata.find_one(userquery)['IceSkatingDec']

    form3.OtherIndoorJan.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJan']
    form3.OtherIndoorFeb.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorFeb']
    form3.OtherIndoorMar.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorMar']
    form3.OtherIndoorApr.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorApr']
    form3.OtherIndoorMay.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorMay']
    form3.OtherIndoorJun.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJun']
    form3.OtherIndoorJul.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJul']
    form3.OtherIndoorAug.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorAug']
    form3.OtherIndoorSep.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorSep']
    form3.OtherIndoorOct.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorOct']
    form3.OtherIndoorNov.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorNov']
    form3.OtherIndoorDec.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorDec']

    form4.SprayIrrigationJan.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJan']
    form4.SprayIrrigationFeb.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationFeb']
    form4.SprayIrrigationMar.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationMar']
    form4.SprayIrrigationApr.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationApr']
    form4.SprayIrrigationMay.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationMay']
    form4.SprayIrrigationJun.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJun']
    form4.SprayIrrigationJul.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJul']
    form4.SprayIrrigationAug.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationAug']
    form4.SprayIrrigationSep.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationSep']
    form4.SprayIrrigationOct.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationOct']
    form4.SprayIrrigationNov.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationNov']
    form4.SprayIrrigationDec.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationDec']

    form4.DripIrrigationJan.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJan']
    form4.DripIrrigationFeb.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationFeb']
    form4.DripIrrigationMar.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationMar']
    form4.DripIrrigationApr.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationApr']
    form4.DripIrrigationMay.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationMay']
    form4.DripIrrigationJun.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJun']
    form4.DripIrrigationJul.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJul']
    form4.DripIrrigationAug.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationAug']
    form4.DripIrrigationSep.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationSep']
    form4.DripIrrigationOct.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationOct']
    form4.DripIrrigationNov.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationNov']
    form4.DripIrrigationDec.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationDec']

    form4.VehicularWashingJan.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJan']
    form4.VehicularWashingFeb.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingFeb']
    form4.VehicularWashingMar.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingMar']
    form4.VehicularWashingApr.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingApr']
    form4.VehicularWashingMay.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingMay']
    form4.VehicularWashingJun.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJun']
    form4.VehicularWashingJul.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJul']
    form4.VehicularWashingAug.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingAug']
    form4.VehicularWashingSep.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingSep']
    form4.VehicularWashingOct.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingOct']
    form4.VehicularWashingNov.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingNov']
    form4.VehicularWashingDec.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingDec']

    form4.OtherOutdoorJan.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJan']
    form4.OtherOutdoorFeb.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorFeb']
    form4.OtherOutdoorMar.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorMar']
    form4.OtherOutdoorApr.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorApr']
    form4.OtherOutdoorMay.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorMay']
    form4.OtherOutdoorJun.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJun']
    form4.OtherOutdoorJul.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJul']
    form4.OtherOutdoorAug.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorAug']
    form4.OtherOutdoorSep.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorSep']
    form4.OtherOutdoorOct.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorOct']
    form4.OtherOutdoorNov.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorNov']
    form4.OtherOutdoorDec.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorDec']

    form5.start_point.data = mongo.db.tankdata.find_one(userquery)['start_point']
    form5.end_point.data = mongo.db.tankdata.find_one(userquery)['end_point']
    form5.step.data = mongo.db.tankdata.find_one(userquery)['step']
    form5.init_fill.data = mongo.db.tankdata.find_one(userquery)['init_fill']
    form5.rel_percent.data = mongo.db.tankdata.find_one(userquery)['rel_percent']



    html_str = mongo.db.tankdata.find_one(userquery)['html_str_g']


    return render_template('Report.html', form1=form1, form2=form2, form3=form3, form4=form4, form5=form5, figstr = html_str)


@app.route('/register_data', methods=['GET', 'POST'])
def register_data():
    form = RegistrationForm()

    if form.validate_on_submit():
        uname = form.email.data
        password = form.password.data
        email = form.email.data
        address = form.address.data
        company = form.company.data
        title = form.company.data

        def_dict = mongo.db.tankdata.find_one({"username": "default"})
        def_dict.pop('_id', None)
        def_dict['username'] = uname
        def_dict['email'] = email
        def_dict['password'] = password
        def_dict['address'] = address
        def_dict['company'] = company
        def_dict['title'] = title

        mongo.db.tankdata.insert_one(def_dict)

        # mongo.db.tankdata.insert_one({"username": form.email.data, "password": form.password.data})
        return redirect(url_for('index'))

    return render_template('register.html', form=form)


@app.route('/login_form', methods=['GET', 'POST'])
def login_data():
    form = LoginForm()
    if form.validate_on_submit():
        print(form.email.data)

        res = mongo.db.tankdata.find_one({"username": form.email.data, "password": form.password.data})
        print(res)
        if res is None:
            print('username not found')
            return render_template('login.html', form=form)
        else:
            session['uid'] = res['username']
            return redirect(url_for('user_index'))

    return render_template('login.html', form=form)


@app.route('/result', methods=['GET', 'POST'])
def res_page():
    return render_template('result.html')


@app.route('/reliability_graph', methods=['GET', 'POST'])
def rel_graph():
    form = GraphQuery()
    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    if form.is_submitted():
        for key in request.form.keys():
            mongo.db.tankdata.update_one(userquery, {"$set": {key: conv_float(request.form[key])}})

        filename = mongo.db.tankdata.find_one(userquery)['RainDataFile']
        start_point = form.start_point.data
        stop = form.end_point.data
        step = form.step.data

        tank_size = [i for i in range(int(start_point), int(stop), int(step))]
        reliable_fill = form.rel_percent.data / 100
        area, run_off_coef, demand = get_data(userquery)

        data = pd.read_csv('data/' + filename, header=0, parse_dates=[0], usecols=['Date', 'Precipitation'])
        data['Precipitation'] = [conv_float(i) for i in data['Precipitation']]
        data = data.dropna()
        col_water = []

        for i in range(0, data.shape[0]):
            if i > 3 and data['Precipitation'][i - 1] <= 0.0 and data['Precipitation'][i - 2] <= 0.0 and \
                    data['Precipitation'][i - 3] <= 0.0:
                modarea = np.subtract(area, np.multiply(area, 0.00138))
                col_water.append(np.sum(
                    np.multiply(np.multiply(modarea, run_off_coef), data['Precipitation'][i])) * 7.5)
            else:
                col_water.append(np.sum(
                    np.multiply(np.multiply(area, run_off_coef), data['Precipitation'][i])) * 7.5)

        av_demand = [
            np.sum(np.concatenate((np.array(demand[data['Date'][i].month - 1][0:2]),
                                   np.divide(demand[data['Date'][i].month - 1][2:],
                                             monthrange(data['Date'][i].year, data['Date'][i].month)[1]))))
            for i in range(0, data.shape[0])]

        # print([np.array(demand[data['Date'][i].month - 1][0:2]) for i in range(0, data.shape[0])])

        # reliability = reliability_2v1(data, tank_size, reliable_fill)
        reliability = reliability_2v2(data, col_water, av_demand, tank_size, reliable_fill, form.init_fill.data / 100)
        rel_change = np.absolute(np.diff(reliability))
        rel_change = np.insert(rel_change, 0, reliability[0])

        # print(reliability)

        fig = plt.figure(figsize=(10, 6))
        for i in range(0, len(tank_size)):
            if rel_change[i] < 0.3:
                plt.plot(tank_size[i], reliability[i], 'yo')
            elif 0.3 < rel_change[i] < 0.5:
                plt.plot(tank_size[i], reliability[i], 'ro')
            else:
                plt.plot(tank_size[i], reliability[i], 'bo')

        plt.xlabel('tank size in gallons')
        plt.ylabel('reliability in %')
        plt.ion()
        plt.grid()
        html_str = mpld3.fig_to_html(fig)
        mongo.db.tankdata.update_one(userquery, {"$set": {"html_str_g": html_str}})

        '''
        fig2 = plt.figure(figsize=(10, 6))
        plt.plot(data['Date'],av_demand)
        plt.xlabel('Dates')
        plt.ylabel('Demands')
        html_str_2 = mpld3.fig_to_html(fig2)
        '''
        # return render_template('relgraph.html', form=form, figstr=html_str, figstr2= html_str_2)
        return render_template('relgraph.html', form=form, figstr=html_str)

    return render_template('relgraph.html', form=form)


@app.route('/water_in_tank', methods=['GET', 'POST'])
def tank_water():
    form = WaterPlotQuery()
    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    if form.is_submitted():
        userquery = {"username": uname}
        filename = mongo.db.tankdata.find_one(userquery)['RainDataFile']
        tank_size = form.tanksize.data
        rel_percent = form.rel_percent.data
        init_fill = form.init_fill.data
        reliable_fill = form.rel_percent.data / 100
        area, run_off_coef, demand = get_data(userquery)
        data = pd.read_csv('data/' + filename, header=0, parse_dates=[0], usecols=['Date', 'Precipitation'])
        data['Precipitation'] = [conv_float(i) for i in data['Precipitation']]
        data = data.dropna()
        col_water = []

        for i in range(0, data.shape[0]):
            if i > 3 and data['Precipitation'][i - 1] <= 0.0 and data['Precipitation'][i - 2] <= 0.0 and \
                    data['Precipitation'][i - 3] <= 0.0:
                modarea = np.subtract(area, np.multiply(area, 0.00138))
                col_water.append(np.sum(
                    np.multiply(np.multiply(modarea, run_off_coef), data['Precipitation'][i] / 12)) * 7.5)
            else:
                col_water.append(np.sum(
                    np.multiply(np.multiply(area, run_off_coef), data['Precipitation'][i] / 12)) * 7.5)

        av_demand = [
            np.sum(np.concatenate((np.array(demand[data['Date'][i].month - 1][0:2]),
                                   np.divide(demand[data['Date'][i].month - 1][2:],
                                             monthrange(data['Date'][i].year, data['Date'][i].month)[1]))))
            for i in range(0, data.shape[0])]

        water, reliability = reliability_and_water_1(data, col_water, av_demand, tank_size, reliable_fill, init_fill)

        html_str = "Reliability is %.2f percent" % (reliability)

        return render_template('water_in_tank.html', form=form, figstr=html_str)

    return render_template('water_in_tank.html', form=form)


def get_data(userquery):
    area = []
    area.append(mongo.db.tankdata.find_one(userquery)['RoofMembraneArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['RoofMetalArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['RoofGreenRoofArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['RoofTerracottaArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['RoofOtherArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousAsphaultArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousBrickArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousOtherArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandyFlatArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandyAvArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandySteepArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayFlatArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayAvArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClaySteepArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGravelArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousLandScapeArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['SemiperviousForestedArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['EngineeredSemiperviousArea'])
    area.append(mongo.db.tankdata.find_one(userquery)['OtherArea'])

    run_off_coef = []
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofMembraneRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofMetalRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofGreenRoofRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofTerracottaRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['RoofOtherRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousAsphaultRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousBrickRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['NonRoofImperviousOtherRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandyFlatRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandyAvRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfSandySteepRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayFlatRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayAvRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClaySteepRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousGravelRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousLandScapeRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['SemiperviousForestedRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['EngineeredSemiperviousRunoffCoeff'])
    run_off_coef.append(mongo.db.tankdata.find_one(userquery)['OtherRunoffCoeff'])

    demand = []
    for i in range(0, 12):
        temp = []
        demand.append(temp)

    num_flushes = mongo.db.tankdata.find_one(userquery)['AvFlushperPerson']
    gal_per_flush_t = mongo.db.tankdata.find_one(userquery)['AvGalperFlushToilets']
    gal_per_flush_u = mongo.db.tankdata.find_one(userquery)['AvGalperFlushUrinals']

    jan_male = mongo.db.tankdata.find_one(userquery)['OccupJan']
    jan_female = mongo.db.tankdata.find_one(userquery)['UrinalJan']
    demand[0].append(jan_female * num_flushes * gal_per_flush_t + 0.5 * jan_male * num_flushes * gal_per_flush_t)
    demand[0].append(0.5 * jan_male * num_flushes * gal_per_flush_u)
    demand[0].append(mongo.db.tankdata.find_one(userquery)['IceMakingJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['IceSkatingJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingJan'])
    demand[0].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorJan'])

    feb_male = mongo.db.tankdata.find_one(userquery)['OccupFeb']
    feb_female = mongo.db.tankdata.find_one(userquery)['UrinalFeb']
    demand[1].append(feb_female * num_flushes * gal_per_flush_t + 0.5 * feb_male * num_flushes * gal_per_flush_t)
    demand[1].append(0.5 * feb_male * num_flushes * gal_per_flush_u)
    demand[1].append(mongo.db.tankdata.find_one(userquery)['IceMakingFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['IceSkatingFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingFeb'])
    demand[1].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorFeb'])

    mar_male = mongo.db.tankdata.find_one(userquery)['OccupMar']
    mar_female = mongo.db.tankdata.find_one(userquery)['UrinalMar']
    demand[2].append(mar_female * num_flushes * gal_per_flush_t + 0.5 * mar_male * num_flushes * gal_per_flush_t)
    demand[2].append(0.5 * mar_male * num_flushes * gal_per_flush_u)
    demand[2].append(mongo.db.tankdata.find_one(userquery)['IceMakingMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['IceSkatingMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingMar'])
    demand[2].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorMar'])

    apr_male = mongo.db.tankdata.find_one(userquery)['OccupApr']
    apr_female = mongo.db.tankdata.find_one(userquery)['UrinalApr']
    demand[3].append(apr_female * num_flushes * gal_per_flush_t + 0.5 * apr_male * num_flushes * gal_per_flush_t)
    demand[3].append(0.5 * apr_male * num_flushes * gal_per_flush_u)
    demand[3].append(mongo.db.tankdata.find_one(userquery)['IceMakingApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['IceSkatingApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingApr'])
    demand[3].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorApr'])

    may_male = mongo.db.tankdata.find_one(userquery)['OccupMay']
    may_female = mongo.db.tankdata.find_one(userquery)['UrinalMay']
    demand[4].append(may_female * num_flushes * gal_per_flush_t + 0.5 * may_male * num_flushes * gal_per_flush_t)
    demand[4].append(0.5 * may_male * num_flushes * gal_per_flush_u)
    demand[4].append(mongo.db.tankdata.find_one(userquery)['IceMakingMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['IceSkatingMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingMay'])
    demand[4].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorMay'])

    jun_male = mongo.db.tankdata.find_one(userquery)['OccupJun']
    jun_female = mongo.db.tankdata.find_one(userquery)['UrinalJun']
    demand[5].append(jun_female * num_flushes * gal_per_flush_t + 0.5 * jun_male * num_flushes * gal_per_flush_t)
    demand[5].append(0.5 * jun_male * num_flushes * gal_per_flush_u)
    demand[5].append(mongo.db.tankdata.find_one(userquery)['IceMakingJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['IceSkatingJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingJun'])
    demand[5].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorJun'])

    jul_male = mongo.db.tankdata.find_one(userquery)['OccupJul']
    jul_female = mongo.db.tankdata.find_one(userquery)['UrinalJul']
    demand[6].append(jul_female * num_flushes * gal_per_flush_t + 0.5 * jul_male * num_flushes * gal_per_flush_t)
    demand[6].append(0.5 * jul_male * num_flushes * gal_per_flush_u)
    demand[6].append(mongo.db.tankdata.find_one(userquery)['IceMakingJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['IceSkatingJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingJul'])
    demand[6].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorJul'])

    aug_male = mongo.db.tankdata.find_one(userquery)['OccupAug']
    aug_female = mongo.db.tankdata.find_one(userquery)['UrinalAug']
    demand[7].append(aug_female * num_flushes * gal_per_flush_t + 0.5 * aug_male * num_flushes * gal_per_flush_t)
    demand[7].append(0.5 * aug_male * num_flushes * gal_per_flush_u)
    demand[7].append(mongo.db.tankdata.find_one(userquery)['IceMakingAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['IceSkatingAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingAug'])
    demand[7].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorAug'])

    sep_male = mongo.db.tankdata.find_one(userquery)['OccupSep']
    sep_female = mongo.db.tankdata.find_one(userquery)['UrinalSep']
    demand[8].append(sep_female * num_flushes * gal_per_flush_t + 0.5 * sep_male * num_flushes * gal_per_flush_t)
    demand[8].append(0.5 * sep_male * num_flushes * gal_per_flush_u)
    demand[8].append(mongo.db.tankdata.find_one(userquery)['IceMakingSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['IceSkatingSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingSep'])
    demand[8].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorSep'])

    oct_male = mongo.db.tankdata.find_one(userquery)['OccupOct']
    oct_female = mongo.db.tankdata.find_one(userquery)['UrinalOct']
    demand[9].append(oct_female * num_flushes * gal_per_flush_t + 0.5 * oct_male * num_flushes * gal_per_flush_t)
    demand[9].append(0.5 * oct_male * num_flushes * gal_per_flush_u)
    demand[9].append(mongo.db.tankdata.find_one(userquery)['IceMakingOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['IceSkatingOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingOct'])
    demand[9].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorOct'])

    nov_male = mongo.db.tankdata.find_one(userquery)['OccupNov']
    nov_female = mongo.db.tankdata.find_one(userquery)['UrinalNov']
    demand[10].append(nov_female * num_flushes * gal_per_flush_t + 0.5 * nov_male * num_flushes * gal_per_flush_t)
    demand[10].append(0.5 * nov_male * num_flushes * gal_per_flush_u)
    demand[10].append(mongo.db.tankdata.find_one(userquery)['IceMakingNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['IceSkatingNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingNov'])
    demand[10].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorNov'])

    dec_male = mongo.db.tankdata.find_one(userquery)['OccupDec']
    dec_female = mongo.db.tankdata.find_one(userquery)['UrinalDec']
    demand[11].append(dec_female * num_flushes * gal_per_flush_t + 0.5 * dec_male * num_flushes * gal_per_flush_t)
    demand[11].append(0.5 * dec_male * num_flushes * gal_per_flush_u)
    demand[11].append(mongo.db.tankdata.find_one(userquery)['IceMakingDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['CoolingTowerDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['IceSkatingDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['OtherIndoorDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['SprayIrrigationDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['DripIrrigationDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['VehicularWashingDec'])
    demand[11].append(mongo.db.tankdata.find_one(userquery)['OtherOutdoorDec'])
    return area, run_off_coef, demand


def reliability_2v2(data, col_water, av_demand, tank_size, reliable_fill, init_fill):
    reliability = []
    for ij in tank_size:
        count = 0
        for i in range(0, data.shape[0]):
            if i == 0:
                water = ij * init_fill + col_water[i] - av_demand[i]
            else:
                water = water + col_water[i] - av_demand[i]

            if water < 0:
                water = 0.0
            elif water > ij:
                water = ij

            if water > reliable_fill * ij:
                count += 1

        reliability.append(count / data.shape[0] * 100)

    return reliability


def reliability_and_water_1(data, col_water, av_demand, tank_size, reliable_fill, init_fill):
    temp_water = []
    count = 0
    for i in range(0, data.shape[0]):
        if i == 0:
            water = tank_size * init_fill + col_water[i] - av_demand[i]
        else:
            water = water + col_water[i] - av_demand[i]

        if water < 0:
            water = 0.0
        elif water > tank_size:
            water = tank_size

        if water > reliable_fill * tank_size:
            count += 1

        temp_water.append(water)

    reliability = count / data.shape[0] * 100

    return temp_water, reliability


@app.route('/roof_collection_area', methods=['GET', 'POST'])
def roof_collection_area():
    form = RoofArea()
    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    form.RoofMembraneArea.data = mongo.db.tankdata.find_one(userquery)['RoofMembraneArea']
    form.RoofMembraneRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofMembraneRunoffCoeff']
    form.RoofAsphaultShingleArea.data = mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleArea']
    form.RoofAsphaultShingleRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofAsphaultShingleRunoffCoeff']
    form.RoofMetalArea.data = mongo.db.tankdata.find_one(userquery)['RoofMetalArea']
    form.RoofMetalRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofMetalRunoffCoeff']
    form.RoofGreenRoofArea.data = mongo.db.tankdata.find_one(userquery)['RoofGreenRoofArea']
    form.RoofGreenRoofRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofGreenRoofRunoffCoeff']
    form.RoofTerracottaArea.data = mongo.db.tankdata.find_one(userquery)['RoofTerracottaArea']
    form.RoofTerracottaRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofTerracottaRunoffCoeff']
    form.RoofOtherArea.data = mongo.db.tankdata.find_one(userquery)['RoofOtherArea']
    form.RoofOtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['RoofOtherRunoffCoeff']

    if form.is_submitted():
        for key in request.form.keys():
            mongo.db.tankdata.update_one(userquery, {"$set": {key: conv_float(request.form[key])}})
        return redirect(url_for('collectareadat'))

    return render_template('RoofCollectionArea.html', form=form)


@app.route('/non_roof_collection_area', methods=['GET', 'POST'])
def non_roof_collection_area():
    form = NonRoofArea()

    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    form.NonRoofImperviousAsphaultArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousAsphaultArea']
    form.NonRoofImperviousAsphaultRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousAsphaultRunoffCoeff']
    form.NonRoofImperviousBrickArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousBrickArea']
    form.NonRoofImperviousBrickRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousBrickRunoffCoeff']
    form.NonRoofImperviousOtherArea.data = mongo.db.tankdata.find_one(userquery)['NonRoofImperviousOtherArea']
    form.NonRoofImperviousOtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'NonRoofImperviousOtherRunoffCoeff']

    form.SemiperviousGrassTurfSandyFlatArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyFlatArea']
    form.SemiperviousGrassTurfSandyFlatRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyFlatRunoffCoeff']

    form.SemiperviousGrassTurfSandyAvArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyAvArea']
    form.SemiperviousGrassTurfSandyAvRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandyAvRunoffCoeff']

    form.SemiperviousGrassTurfSandySteepArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandySteepArea']
    form.SemiperviousGrassTurfSandySteepRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfSandySteepRunoffCoeff']
    form.SemiperviousGrassTurfClayFlatArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayFlatArea']
    form.SemiperviousGrassTurfClayFlatRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayFlatRunoffCoeff']
    form.SemiperviousGrassTurfClayAvArea.data = mongo.db.tankdata.find_one(userquery)['SemiperviousGrassTurfClayAvArea']
    form.SemiperviousGrassTurfClayAvRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClayAvRunoffCoeff']
    form.SemiperviousGrassTurfClaySteepArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClaySteepArea']
    form.SemiperviousGrassTurfClaySteepRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGrassTurfClaySteepRunoffCoeff']

    form.SemiperviousGravelArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGravelArea']
    form.SemiperviousGravelRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousGravelRunoffCoeff']

    form.SemiperviousLandScapeArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousLandScapeArea']
    form.SemiperviousLandScapeRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousLandScapeRunoffCoeff']

    form.SemiperviousForestedArea.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousForestedArea']
    form.SemiperviousForestedRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'SemiperviousForestedRunoffCoeff']

    form.EngineeredSemiperviousArea.data = mongo.db.tankdata.find_one(userquery)[
        'EngineeredSemiperviousArea']
    form.EngineeredSemiperviousRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)[
        'EngineeredSemiperviousRunoffCoeff']
    form.OtherArea.data = mongo.db.tankdata.find_one(userquery)['OtherArea']
    form.OtherRunoffCoeff.data = mongo.db.tankdata.find_one(userquery)['OtherRunoffCoeff']

    if form.is_submitted():
        for key in request.form.keys():
            mongo.db.tankdata.update_one(userquery, {"$set": {key: conv_float(request.form[key])}})

        return redirect(url_for('collectareadat'))

    return render_template('NonRoofCollectionArea.html', form=form)


@app.route('/indoor_demand', methods=['GET', 'POST'])
def indoordemand():
    form = IndoorDemand()
    uname = session.get('uid')
    userquery = {"username": uname}

    form.AvFlushperPerson.data = mongo.db.tankdata.find_one(userquery)['AvFlushperPerson']
    form.AvGalperFlushToilets.data = mongo.db.tankdata.find_one(userquery)['AvGalperFlushToilets']
    form.AvGalperFlushUrinals.data = mongo.db.tankdata.find_one(userquery)['AvGalperFlushUrinals']

    form.OccupJan.data = mongo.db.tankdata.find_one(userquery)['OccupJan']
    form.OccupFeb.data = mongo.db.tankdata.find_one(userquery)['OccupFeb']
    form.OccupMar.data = mongo.db.tankdata.find_one(userquery)['OccupMar']
    form.OccupApr.data = mongo.db.tankdata.find_one(userquery)['OccupApr']
    form.OccupMay.data = mongo.db.tankdata.find_one(userquery)['OccupMay']
    form.OccupJun.data = mongo.db.tankdata.find_one(userquery)['OccupJun']
    form.OccupJul.data = mongo.db.tankdata.find_one(userquery)['OccupJul']
    form.OccupAug.data = mongo.db.tankdata.find_one(userquery)['OccupAug']
    form.OccupSep.data = mongo.db.tankdata.find_one(userquery)['OccupSep']
    form.OccupOct.data = mongo.db.tankdata.find_one(userquery)['OccupOct']
    form.OccupNov.data = mongo.db.tankdata.find_one(userquery)['OccupNov']
    form.OccupDec.data = mongo.db.tankdata.find_one(userquery)['OccupDec']

    form.UrinalJan.data = mongo.db.tankdata.find_one(userquery)['UrinalJan']
    form.UrinalFeb.data = mongo.db.tankdata.find_one(userquery)['UrinalFeb']
    form.UrinalMar.data = mongo.db.tankdata.find_one(userquery)['UrinalMar']
    form.UrinalApr.data = mongo.db.tankdata.find_one(userquery)['UrinalApr']
    form.UrinalMay.data = mongo.db.tankdata.find_one(userquery)['UrinalMay']
    form.UrinalJun.data = mongo.db.tankdata.find_one(userquery)['UrinalJun']
    form.UrinalJul.data = mongo.db.tankdata.find_one(userquery)['UrinalJul']
    form.UrinalAug.data = mongo.db.tankdata.find_one(userquery)['UrinalAug']
    form.UrinalSep.data = mongo.db.tankdata.find_one(userquery)['UrinalSep']
    form.UrinalOct.data = mongo.db.tankdata.find_one(userquery)['UrinalOct']
    form.UrinalNov.data = mongo.db.tankdata.find_one(userquery)['UrinalNov']
    form.UrinalDec.data = mongo.db.tankdata.find_one(userquery)['UrinalDec']

    form.IceMakingJan.data = mongo.db.tankdata.find_one(userquery)['IceMakingJan']
    form.IceMakingFeb.data = mongo.db.tankdata.find_one(userquery)['IceMakingFeb']
    form.IceMakingMar.data = mongo.db.tankdata.find_one(userquery)['IceMakingMar']
    form.IceMakingApr.data = mongo.db.tankdata.find_one(userquery)['IceMakingApr']
    form.IceMakingMay.data = mongo.db.tankdata.find_one(userquery)['IceMakingMay']
    form.IceMakingJun.data = mongo.db.tankdata.find_one(userquery)['IceMakingJun']
    form.IceMakingJul.data = mongo.db.tankdata.find_one(userquery)['IceMakingJul']
    form.IceMakingAug.data = mongo.db.tankdata.find_one(userquery)['IceMakingAug']
    form.IceMakingSep.data = mongo.db.tankdata.find_one(userquery)['IceMakingSep']
    form.IceMakingOct.data = mongo.db.tankdata.find_one(userquery)['IceMakingOct']
    form.IceMakingNov.data = mongo.db.tankdata.find_one(userquery)['IceMakingNov']
    form.IceMakingDec.data = mongo.db.tankdata.find_one(userquery)['IceMakingDec']

    form.CoolingTowerJan.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJan']
    form.CoolingTowerFeb.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerFeb']
    form.CoolingTowerMar.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerMar']
    form.CoolingTowerApr.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerApr']
    form.CoolingTowerMay.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerMay']
    form.CoolingTowerJun.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJun']
    form.CoolingTowerJul.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerJul']
    form.CoolingTowerAug.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerAug']
    form.CoolingTowerSep.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerSep']
    form.CoolingTowerOct.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerOct']
    form.CoolingTowerNov.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerNov']
    form.CoolingTowerDec.data = mongo.db.tankdata.find_one(userquery)['CoolingTowerDec']

    form.IceSkatingJan.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJan']
    form.IceSkatingFeb.data = mongo.db.tankdata.find_one(userquery)['IceSkatingFeb']
    form.IceSkatingMar.data = mongo.db.tankdata.find_one(userquery)['IceSkatingMar']
    form.IceSkatingApr.data = mongo.db.tankdata.find_one(userquery)['IceSkatingApr']
    form.IceSkatingMay.data = mongo.db.tankdata.find_one(userquery)['IceSkatingMay']
    form.IceSkatingJun.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJun']
    form.IceSkatingJul.data = mongo.db.tankdata.find_one(userquery)['IceSkatingJul']
    form.IceSkatingAug.data = mongo.db.tankdata.find_one(userquery)['IceSkatingAug']
    form.IceSkatingSep.data = mongo.db.tankdata.find_one(userquery)['IceSkatingSep']
    form.IceSkatingOct.data = mongo.db.tankdata.find_one(userquery)['IceSkatingOct']
    form.IceSkatingNov.data = mongo.db.tankdata.find_one(userquery)['IceSkatingNov']
    form.IceSkatingDec.data = mongo.db.tankdata.find_one(userquery)['IceSkatingDec']

    form.OtherIndoorJan.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJan']
    form.OtherIndoorFeb.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorFeb']
    form.OtherIndoorMar.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorMar']
    form.OtherIndoorApr.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorApr']
    form.OtherIndoorMay.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorMay']
    form.OtherIndoorJun.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJun']
    form.OtherIndoorJul.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorJul']
    form.OtherIndoorAug.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorAug']
    form.OtherIndoorSep.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorSep']
    form.OtherIndoorOct.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorOct']
    form.OtherIndoorNov.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorNov']
    form.OtherIndoorDec.data = mongo.db.tankdata.find_one(userquery)['OtherIndoorDec']

    if form.is_submitted():
        for key in request.form.keys():
            mongo.db.tankdata.update_one(userquery, {"$set": {key: conv_float(request.form[key])}})
        return redirect(url_for('demanddat'))

    return render_template('IndoorDemand.html', form=form)


@app.route('/outdoor_demand', methods=['GET', 'POST'])
def outdoordemand():
    form = OutdoorDemand()
    uname = session.get('uid')
    userquery = {"username": uname}

    form.SprayIrrigationJan.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJan']
    form.SprayIrrigationFeb.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationFeb']
    form.SprayIrrigationMar.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationMar']
    form.SprayIrrigationApr.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationApr']
    form.SprayIrrigationMay.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationMay']
    form.SprayIrrigationJun.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJun']
    form.SprayIrrigationJul.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationJul']
    form.SprayIrrigationAug.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationAug']
    form.SprayIrrigationSep.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationSep']
    form.SprayIrrigationOct.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationOct']
    form.SprayIrrigationNov.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationNov']
    form.SprayIrrigationDec.data = mongo.db.tankdata.find_one(userquery)['SprayIrrigationDec']

    form.DripIrrigationJan.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJan']
    form.DripIrrigationFeb.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationFeb']
    form.DripIrrigationMar.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationMar']
    form.DripIrrigationApr.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationApr']
    form.DripIrrigationMay.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationMay']
    form.DripIrrigationJun.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJun']
    form.DripIrrigationJul.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationJul']
    form.DripIrrigationAug.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationAug']
    form.DripIrrigationSep.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationSep']
    form.DripIrrigationOct.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationOct']
    form.DripIrrigationNov.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationNov']
    form.DripIrrigationDec.data = mongo.db.tankdata.find_one(userquery)['DripIrrigationDec']

    form.VehicularWashingJan.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJan']
    form.VehicularWashingFeb.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingFeb']
    form.VehicularWashingMar.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingMar']
    form.VehicularWashingApr.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingApr']
    form.VehicularWashingMay.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingMay']
    form.VehicularWashingJun.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJun']
    form.VehicularWashingJul.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingJul']
    form.VehicularWashingAug.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingAug']
    form.VehicularWashingSep.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingSep']
    form.VehicularWashingOct.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingOct']
    form.VehicularWashingNov.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingNov']
    form.VehicularWashingDec.data = mongo.db.tankdata.find_one(userquery)['VehicularWashingDec']

    form.OtherOutdoorJan.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJan']
    form.OtherOutdoorFeb.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorFeb']
    form.OtherOutdoorMar.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorMar']
    form.OtherOutdoorApr.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorApr']
    form.OtherOutdoorMay.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorMay']
    form.OtherOutdoorJun.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJun']
    form.OtherOutdoorJul.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorJul']
    form.OtherOutdoorAug.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorAug']
    form.OtherOutdoorSep.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorSep']
    form.OtherOutdoorOct.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorOct']
    form.OtherOutdoorNov.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorNov']
    form.OtherOutdoorDec.data = mongo.db.tankdata.find_one(userquery)['OtherOutdoorDec']

    if form.is_submitted():
        for key in request.form.keys():
            mongo.db.tankdata.update_one(userquery, {"$set": {key: conv_float(request.form[key])}})
        return redirect(url_for('demanddat'))

    return render_template('OutdoorDemand.html', form=form)


@app.route('/rain_fall_data', methods=['GET', 'POST'])
def rainfalldata():
    form = Raindata()
    uname = session.get('uid')
    if uname is None:
        return redirect(url_for('login_data'))
    else:
        userquery = {"username": uname}

    if form.is_submitted():
        print(form.input_file.data)
        # data = request.files[form.input_file.name].read()
        # print(data)
        file = request.files[form.input_file.name]
        filename = secure_filename(file.filename)
        filename = filename[:-4] + '--' + uname + '.csv'
        print(filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        mongo.db.tankdata.update_one(userquery, {"$set": {"RainDataFile": filename}})

        return redirect(url_for('user_index'))

    return render_template('fileupload.html', form=form)


if __name__ == '__main__':
    app.run(debug=True)
