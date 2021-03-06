# import_export_batches/controllers.py
# Brought to you by We Vote. Be good.
# -*- coding: UTF-8 -*-

from ballot.models import MEASURE, CANDIDATE, POLITICIAN
from .models import CONTEST_OFFICE, ELECTED_OFFICE, CREATE, ADD_TO_EXISTING
from candidate.models import CandidateCampaignManager
from config.base import get_environment_variable
import copy
from exception.models import handle_record_found_more_than_one_exception
from position.models import PositionManager, PERCENT_RATING
import requests
from voter_guide.models import ORGANIZATION_WORD
import wevote_functions.admin
from wevote_functions.functions import positive_value_exists, extract_twitter_handle_from_text_string
from .models import BatchManager, BatchDescription, BatchHeaderMap, BatchRow, BatchRowActionOrganization, \
    BatchRowActionMeasure, BatchRowActionElectedOffice, BatchRowActionContestOffice, BatchRowActionPolitician
from measure.models import ContestMeasure
from office.models import ContestOffice, ElectedOffice, ElectedOfficeManager
from politician.models import Politician
from electoral_district.controllers import retrieve_electoral_district
from exception.models import handle_exception

logger = wevote_functions.admin.get_logger(__name__)

# VOTE_SMART_API_KEY = get_environment_variable("VOTE_SMART_API_KEY")


def create_batch_row_actions(batch_header_id, batch_row_id):
    """
    Cycle through all BatchRow entries for this batch_header_id and move the values we can find into
    the BatchRowActionYYY table so we can review it before importing it
    :param batch_header_id:
    :param batch_row_id:
    :return:
    """
    success = False
    status = ""
    number_of_batch_actions_created = 0
    kind_of_batch = ""

    if not positive_value_exists(batch_header_id):
        status = "CREATE_BATCH_ROW_ACTIONS-BATCH_HEADER_ID_MISSING"
        results = {
            'success': success,
            'status': status,
            'batch_header_id': batch_header_id,
            'kind_of_batch': kind_of_batch,
            'batch_actions_created': success,
            'number_of_batch_actions_created': number_of_batch_actions_created,
        }
        return results

    try:
        batch_description = BatchDescription.objects.get(batch_header_id=batch_header_id)
        batch_description_found = True
    except BatchDescription.DoesNotExist:
        # This is fine
        batch_description = BatchDescription()
        batch_description_found = False

    if batch_description_found:
        kind_of_batch = batch_description.kind_of_batch

        try:
            batch_header_map = BatchHeaderMap.objects.get(batch_header_id=batch_header_id)
            batch_header_map_found = True
        except BatchHeaderMap.DoesNotExist:
            # This is fine
            batch_header_map = BatchHeaderMap()
            batch_header_map_found = False

    if batch_header_map_found:
        batch_row_list_found = False
        try:
            batch_row_list = BatchRow.objects.all()
            batch_row_list = batch_row_list.filter(batch_header_id=batch_header_id)
            if positive_value_exists(batch_row_id):
                batch_row_list = batch_row_list.filter(id=batch_row_id)

            if len(batch_row_list):
                batch_row_list_found = True
        except BatchDescription.DoesNotExist:
            # This is fine
            batch_row_list = []
            batch_row_list_found = False
            pass

    if batch_description_found and batch_header_map_found and batch_row_list_found:
        for one_batch_row in batch_row_list:
            if kind_of_batch == ORGANIZATION_WORD:
                batch_row_action_organization = BatchRowActionOrganization()
                # Does a BatchRowActionOrganization entry already exist?
                existing_results = batch_row_action_organization.retrieve_batch_row_action_organization(
                    batch_header_id, one_batch_row.id)
                if existing_results['batch_row_action_found']:
                    batch_row_action_organization = existing_results['batch_row_action_organization']
                else:
                    # If a BatchRowActionOrganization entry does not exist, create one
                    new_results = create_batch_row_action_organization(batch_description, batch_header_map,
                                                                       one_batch_row)
                    if new_results['batch_row_action_created']:
                        batch_row_action_organization = new_results['batch_row_action_organization']
                        number_of_batch_actions_created += 1
                    else:
                        # Move on to the next batch_row
                        continue
                # Now check for warnings (like "this is a duplicate"). If warnings are found,
                # add the warning to batch_row_action_organization entry
                # batch_row_action_organization.kind_of_action = "TEST"
                batch_row_action_organization.save()

            elif kind_of_batch == MEASURE:
                results = create_batch_row_action_measure(batch_description, batch_header_map, one_batch_row)

                if results['new_action_measure_created']:
                    # for now, do not handle batch_row_action_measure data
                    # batch_row_action_measure = results['batch_row_action_measure']
                    number_of_batch_actions_created += 1
                    success = True
            elif kind_of_batch == ELECTED_OFFICE:
                results = create_batch_row_action_elected_office(batch_description, batch_header_map, one_batch_row)

                if results['new_action_elected_office_created']:
                    # for now, do not handle batch_row_action_elected_office data
                    # batch_row_action_elected_office = results['batch_row_action_elected_office']
                    number_of_batch_actions_created += 1
                    success = True
            elif kind_of_batch == CONTEST_OFFICE:
                    results = create_batch_row_action_contest_office(batch_description, batch_header_map, one_batch_row)

                    if results['new_action_contest_office_created']:
                        # for now, do not handle batch_row_action_contest_office data
                        # batch_row_action_contest_office = results['batch_row_action_contest_office']
                        number_of_batch_actions_created += 1
                        success = True
            elif kind_of_batch == POLITICIAN:
                results = create_batch_row_action_politician(batch_description, batch_header_map, one_batch_row)

                if results['new_action_politician_created']:
                    # for now, do not handle batch_row_action_politician data
                    # batch_row_action_politician = results['batch_row_action_politician']
                    number_of_batch_actions_created += 1
                    success = True
                # Now check for warnings (like "this is a duplicate"). If warnings are found,
                # add the warning to batch_row_action_measure entry
                # batch_row_action_measure.kind_of_action = "TEST"

    results = {
        'success': success,
        'status': status,
        'batch_header_id': batch_header_id,
        'kind_of_batch': kind_of_batch,
        'batch_actions_created': success,
        'number_of_batch_actions_created': number_of_batch_actions_created,
    }
    return results


def create_batch_row_action_organization(batch_description, batch_header_map, one_batch_row):
    batch_row_action_organization = BatchRowActionOrganization()
    # Find the column in the incoming batch_row with the header == organization_name
    organization_name = batch_row_action_organization.retrieve_value_from_batch_row("organization_name",
                                                                                    batch_header_map, one_batch_row)
    # Find the column in the incoming batch_row with the header == state_code
    state_served_code = batch_row_action_organization.retrieve_value_from_batch_row("state_code", batch_header_map,
                                                                                    one_batch_row)

    try:
        batch_row_action_organization = BatchRowActionOrganization.objects.create(
            batch_header_id=batch_description.batch_header_id,
            batch_row_id=one_batch_row.id,
            state_served_code=state_served_code,
            organization_name=organization_name,
        )
        batch_row_action_created = True
        success = True
        status = "BATCH_ROW_ACTION_ORGANIZATION_CREATED"
    except Exception as e:
        batch_row_action_created = False
        batch_row_action_organization = BatchRowActionOrganization()
        success = False
        status = "BATCH_ROW_ACTION_ORGANIZATION_NOT_CREATED"
        handle_exception(e, logger=logger, exception_message=status)

    results = {
        'success': success,
        'status': status,
        'batch_row_action_created': batch_row_action_created,
        'batch_row_action_organization': batch_row_action_organization,
    }
    return results


def create_batch_row_action_measure(batch_description, batch_header_map, one_batch_row):
    """
    Handle batch_row for measure type
    :param batch_description:
    :param batch_header_map:
    :param one_batch_row:
    :return:
    """
    batch_manager = BatchManager()

    # new_action_measure_created = False
    state_code = ''
    batch_row_action_measure_status = ''

    # Find the column in the incoming batch_row with the header == measure_title
    measure_title = batch_manager.retrieve_value_from_batch_row("measure_title", batch_header_map, one_batch_row)
    # Find the column in the incoming batch_row with the header == state_code
    electoral_district_id = batch_manager.retrieve_value_from_batch_row("electoral_district_id", batch_header_map,
                                                                        one_batch_row)
    google_civic_election_id = str(batch_description.google_civic_election_id)

    results = retrieve_electoral_district(electoral_district_id)
    if results['electoral_district_found']:
        if results['state_code_found']:
            state_code = results['state_code']
            # state_code = results.values_list('state_code', flat=True).get()
    else:
        # state_code = ''
        batch_row_action_measure_status = 'ELECTORAL_DISTRICT_NOT_FOUND'
        # kind_of_action = 'TBD'

    measure_text = batch_manager.retrieve_value_from_batch_row("measure_name",
                                                               batch_header_map,
                                                               one_batch_row)
    measure_subtitle = batch_manager.retrieve_value_from_batch_row("measure_sub_title",
                                                                   batch_header_map,
                                                                   one_batch_row)

    # Look up ContestMeasure to see if an entry exists
    contest_measure = ContestMeasure()
    # These three parameters are needed to look up in Contest Measure table for a match
    if positive_value_exists(measure_title) and positive_value_exists(state_code) and \
            positive_value_exists(google_civic_election_id):
        try:
            contest_measure_query = ContestMeasure.objects.all()
            contest_measure_item_list = contest_measure_query.filter(measure_title__iexact=measure_title,
                                                                     state_code__iexact=state_code,
                                                                     google_civic_election_id=google_civic_election_id)

            if contest_measure_item_list or len(contest_measure_item_list):
                # entry exists
                batch_row_action_measure_status = 'BATCH_ROW_ACTION_MEASURE_RETRIEVED'
                # batch_row_action_found = True
                # new_action_measure_created = False
                # success = True
                batch_row_action_measure = contest_measure_item_list
                # if a single entry matches, update that entry
                if len(contest_measure_item_list) == 1:
                    kind_of_action = 'ADD_TO_EXISTING'
                else:
                    # more than one entry found with a match in ContestMeasure
                    kind_of_action = 'DO_NOT_PROCESS'
            else:
                kind_of_action = 'CREATE'
        except ContestMeasure.DoesNotExist:
            batch_row_action_measure = BatchRowActionMeasure()
            # batch_row_action_found = False
            # success = True
            batch_row_action_measure_status = "BATCH_ROW_ACTION_MEASURE_NOT_FOUND"
            kind_of_action = 'TBD'
    else:
        kind_of_action = 'TBD'
        batch_row_action_measure_status = "INSUFFICIENT_DATA_FOR_BATCH_ROW_ACTION_MEASURE_CREATE"
    # Create a new entry in BatchRowActionMeasure
    try:
        updated_values = {
            'measure_title': measure_title,
            'state_code': state_code,
            'measure_text': measure_text,
            'measure_subtitle': measure_subtitle,
            'kind_of_action': kind_of_action,
            'google_civic_election_id': google_civic_election_id,
            'status': batch_row_action_measure_status
        }

        batch_row_action_measure, new_action_measure_created = BatchRowActionMeasure.objects.update_or_create(
            batch_header_id=batch_description.batch_header_id, batch_row_id=one_batch_row.id,
            defaults=updated_values)
        # new_action_measure_created = True
        success = True
        status = "BATCH_ROW_ACTION_MEASURE_CREATED"

    except Exception as e:
        batch_row_action_measure = BatchRowActionMeasure()
        batch_row_action_found = False
        success = False
        new_action_measure_created = False
        status = "BATCH_ROW_ACTION_MEASURE_RETRIEVE_ERROR"
        handle_exception(e, logger=logger, exception_message=status)

    results = {
        'success': success,
        'status': status,
        'new_action_measure_created': new_action_measure_created,
        'batch_row_action_measure': batch_row_action_measure,
    }
    return results


def create_batch_row_action_elected_office(batch_description, batch_header_map, one_batch_row):
    """
    Handle batch_row for elected office
    :param batch_description:
    :param batch_header_map:
    :param one_batch_row:
    :return:
    """
    batch_manager = BatchManager()

    new_action_elected_office_created = False
    state_code = ''
    batch_row_action_elected_office_status = ''
    elected_office_we_vote_id = ''
    success = False
    status = ''

    # Find the column in the incoming batch_row with the header == elected_office_name
    elected_office_name = batch_manager.retrieve_value_from_batch_row("elected_office_name",
                                                                      batch_header_map, one_batch_row)
    # Find the column in the incoming batch_row with the header == state_code
    electoral_district_id = batch_manager.retrieve_value_from_batch_row("electoral_district_id", batch_header_map,
                                                                        one_batch_row)
    google_civic_election_id = str(batch_description.google_civic_election_id)
    results = retrieve_electoral_district(electoral_district_id)
    if results['electoral_district_found']:
        if results['state_code_found']:
            state_code = results['state_code']
    else:
        # state_code = ''
        batch_row_action_office_status = 'ELECTORAL_DISTRICT_NOT_FOUND'
        kind_of_action = 'TBD'

    ctcl_uuid = batch_manager.retrieve_value_from_batch_row("elected_office_ctcl_uuid", batch_header_map, one_batch_row)

    elected_office_description = batch_manager.retrieve_value_from_batch_row("elected_office_description",
                                                                             batch_header_map, one_batch_row)
    elected_office_is_partisan = batch_manager.retrieve_value_from_batch_row("elected_office_is_partisan",
                                                                             batch_header_map, one_batch_row)

    # Look up ElectedOffice to see if an entry exists
    # These three parameters are needed to look up in ElectedOffice table for a match
    if positive_value_exists(elected_office_name) and positive_value_exists(state_code) and \
            positive_value_exists(google_civic_election_id):
        try:
            elected_office_query = ElectedOffice.objects.all()
            elected_office_query = elected_office_query.filter(elected_office_name__iexact=elected_office_name,
                                                               state_code__iexact=state_code,
                                                               google_civic_election_id=google_civic_election_id)

            elected_office_item_list = list(elected_office_query)
            if len(elected_office_item_list):
                # entry exists
                batch_row_action_elected_office_status = 'ELECTED_OFFICE_ENTRY_EXISTS'
                batch_row_action_found = True
                new_action_elected_office_created = False
                # success = True
                # if a single entry matches, update that entry
                if len(elected_office_item_list) == 1:
                    kind_of_action = 'ADD_TO_EXISTING'
                    elected_office_we_vote_id = elected_office_query.first().we_vote_id
                else:
                    # more than one entry found with a match in ElectedOffice
                    kind_of_action = 'DO_NOT_PROCESS'
                    # elected_office_we_vote_id = elected_office_item_list.values('elected_office_we_vote_id')
            else:
                kind_of_action = 'CREATE'
        except ElectedOffice.DoesNotExist:
            batch_row_action_elected_office = BatchRowActionElectedOffice()
            batch_row_action_found = False
            # success = True
            batch_row_action_elected_office_status = "BATCH_ROW_ACTION_ELECTED_OFFICE_NOT_FOUND"
            kind_of_action = 'TBD'
    else:
        kind_of_action = 'TBD'
        batch_row_action_elected_office_status = "INSUFFICIENT_DATA_FOR_BATCH_ROW_ACTION_ELECTED_OFFICE_CREATE"
    # Create a new entry in BatchRowActionElectedOffice
    try:

        # Check if elected_office_name, state_code match exists in BatchRowActionElectedOffice
        # for this header_id (Duplicate entries in the same data set
        existing_batch_row_action_elected_office_query = BatchRowActionElectedOffice.objects.all()
        existing_batch_row_action_elected_office_query = existing_batch_row_action_elected_office_query.filter(
            batch_header_id=batch_description.batch_header_id, elected_office_name=elected_office_name,
            state_code=state_code, google_civic_election_id=google_civic_election_id)
        existing_batch_row_action_elected_office_list = list(existing_batch_row_action_elected_office_query)
        number_of_existing_entries = len(existing_batch_row_action_elected_office_list)
        if not number_of_existing_entries:
            # no entry exists, create one
            updated_values = {
                'elected_office_name': elected_office_name,
                'state_code': state_code,
                'elected_office_description': elected_office_description,
                'ctcl_uuid': ctcl_uuid,
                'elected_office_is_partisan': elected_office_is_partisan,
                'elected_office_we_vote_id': elected_office_we_vote_id,
                'kind_of_action': kind_of_action,
                'google_civic_election_id': google_civic_election_id,
                'status': batch_row_action_elected_office_status
            }

            batch_row_action_elected_office, new_action_elected_office_created = BatchRowActionElectedOffice.objects.\
                update_or_create(batch_header_id=batch_description.batch_header_id, batch_row_id=one_batch_row.id,
                                 defaults=updated_values)
            # new_action_elected_office_created = True
            success = True
            status += "CREATE_BATCH_ROW_ACTION_ELECTED_OFFICE_BATCH_ROW_ACTION_ELECTED_OFFICE_CREATED"
        else:
            # # if batch_header_id is same then it is a duplicate entry?
            existing_elected_office_entry = existing_batch_row_action_elected_office_query.first()
            if one_batch_row.id != existing_elected_office_entry.batch_row_id:
                # duplicate entry, create a new entry but set kind_of_action as DO_NOT_PROCESS and
                # set status as duplicate
                # kind_of_action = 'DO_NOT_PROCESS'
                updated_values = {
                    'elected_office_name': elected_office_name,
                    'state_code': state_code,
                    'elected_office_description': elected_office_description,
                    'ctcl_uuid': ctcl_uuid,
                    'elected_office_is_partisan': elected_office_is_partisan,
                    'elected_office_we_vote_id': elected_office_we_vote_id,
                    'kind_of_action': 'DO_NOT_PROCESS',
                    'google_civic_election_id': google_civic_election_id,
                    'status': 'DUPLICATE_ELECTED_OFFICE_ENTRY'
                }

                batch_row_action_elected_office, new_action_elected_office_created = \
                    BatchRowActionElectedOffice.objects.update_or_create(
                        batch_header_id=batch_description.batch_header_id, batch_row_id=one_batch_row.id,
                        defaults=updated_values)
                status += 'CREATE_BATCH_ROW_ACTION_ELECTED_OFFICE_BATCH_ROW_ACTION_ELECTED_OFFICE_DUPLICATE_ENTRIES'
                success = True
                # this is a duplicate entry, mark it's kind_of_action as DO_NOT_PROCESS and status as duplicate
            else:
                # existing entry but not duplicate
                status += 'BATCH_ROW_ACTION_ELECTED_OFFICE_ENTRY_EXISTS'
                success = True
                batch_row_action_elected_office = existing_batch_row_action_elected_office_query.get()
    except Exception as e:
        batch_row_action_elected_office = BatchRowActionElectedOffice()
        batch_row_action_found = False
        success = False
        new_action_elected_office_created = False
        status = "CREATE_BATCH_ROW_ACTION_ELECTED_OFFICE_BATCH_ROW_ACTION_ELECTED_OFFICE_RETRIEVE_ERROR"
        handle_exception(e, logger=logger, exception_message=status)

    results = {
        'success': success,
        'status': status,
        'new_action_elected_office_created': new_action_elected_office_created,
        'batch_row_action_elected_office': batch_row_action_elected_office,
    }
    return results


def create_batch_row_action_contest_office(batch_description, batch_header_map, one_batch_row):
    """
    Handle batch_row for contest office type
    :param batch_description:
    :param batch_header_map:
    :param one_batch_row:
    :return:
    """
    batch_manager = BatchManager()

    new_action_contest_office_created = False
    state_code = ''
    batch_row_action_contest_office_status = ''

    # Find the column in the incoming batch_row with the header == contest_office_name
    contest_office_name = batch_manager.retrieve_value_from_batch_row("contest_office_name", batch_header_map,
                                                                      one_batch_row)
    # Find the column in the incoming batch_row with the header == state_code
    electoral_district_id = batch_manager.retrieve_value_from_batch_row("electoral_district_id", batch_header_map,
                                                                        one_batch_row)
    google_civic_election_id = str(batch_description.google_civic_election_id)
    results = retrieve_electoral_district(electoral_district_id)
    if results['electoral_district_found']:
        if results['state_code_found']:
            state_code = results['state_code']
    else:
        # state_code = ''
        batch_row_action_contest_office_status = 'ELECTORAL_DISTRICT_NOT_FOUND'
        kind_of_action = 'TBD'

    ctcl_uuid = batch_manager.retrieve_value_from_batch_row("contest_office_ctcl_uuid", batch_header_map, one_batch_row)

    contest_office_description = batch_manager.retrieve_value_from_batch_row("contest_office_description",
                                                                             batch_header_map, one_batch_row)
    contest_office_is_partisan = batch_manager.retrieve_value_from_batch_row("contest_office_is_partisan",
                                                                             batch_header_map, one_batch_row)

    # Look up ContestOffice to see if an entry exists
    # contest_office = ContestOffice()
    # These three parameters are needed to look up in ContestOffice table for a match
    if positive_value_exists(contest_office_name) and positive_value_exists(state_code) and \
            positive_value_exists(google_civic_election_id):
        try:
            contest_office_query = ContestOffice.objects.all()
            contest_office_query = contest_office_query.filter(office_name__iexact=contest_office_name,
                                                               state_code__iexact=state_code,
                                                               google_civic_election_id=google_civic_election_id)

            contest_office_item_list = list(contest_office_query)
            if len(contest_office_item_list):
                # entry exists
                batch_row_action_contest_office_status = 'BATCH_ROW_ACTION_CONTEST_OFFICE_RETRIEVED'
                batch_row_action_found = True
                new_action_contest_office_created = False
                # success = True
                # if a single entry matches, update that entry
                if len(contest_office_item_list) == 1:
                    kind_of_action = 'ADD_TO_EXISTING'
                else:
                    # more than one entry found with a match in ContestOffice
                    kind_of_action = 'DO_NOT_PROCESS'
            else:
                kind_of_action = 'CREATE'
        except ContestOffice.DoesNotExist:
            batch_row_contest_action_office = BatchRowActionContestOffice()
            batch_row_action_found = False
            # success = True
            batch_row_action_contest_office_status = "BATCH_ROW_ACTION_CONTEST_OFFICE_NOT_FOUND"
            kind_of_action = 'TBD'
    else:
        kind_of_action = 'TBD'
        batch_row_action_contest_office_status = "INSUFFICIENT_DATA_FOR_BATCH_ROW_ACTION_CONTEST_OFFICE_CREATE"
    # Create a new entry in BatchRowActionContestOffice
    try:
        updated_values = {
            'contest_office_name': contest_office_name,
            'state_code': state_code,
            'contest_office_description': contest_office_description,
            'ctcl_uuid': ctcl_uuid,
            'contest_office_is_partisan': contest_office_is_partisan,
            'kind_of_action': kind_of_action,
            'google_civic_election_id': google_civic_election_id,
            'status': batch_row_action_contest_office_status
        }

        batch_row_action_contest_office, new_action_contest_office_created = BatchRowActionContestOffice.objects.\
            update_or_create(batch_header_id=batch_description.batch_header_id, batch_row_id=one_batch_row.id,
                             defaults=updated_values)
        # new_action_contest_office_created = True
        success = True
        status = "BATCH_ROW_ACTION_CONTEST_OFFICE_CREATED"

    except Exception as e:
        batch_row_action_contest_office = BatchRowActionContestOffice()
        batch_row_action_found = False
        success = False
        new_action_contest_office_created = False
        status = "BATCH_ROW_ACTION_CONTEST_OFFICE_RETRIEVE_ERROR"
        handle_exception(e, logger=logger, exception_message=status)

    results = {
        'success': success,
        'status': status,
        'new_action_contest_office_created': new_action_contest_office_created,
        'batch_row_action_contest_office': batch_row_action_contest_office,
    }
    return results


def create_batch_row_action_politician(batch_description, batch_header_map, one_batch_row):
    """
    Handle batch_row for politician type
    :param batch_description:
    :param batch_header_map:
    :param one_batch_row:
    :return:
    """
    batch_manager = BatchManager()

    # new_action_politician_created = False
    batch_row_action_politician_status = ''

    # Find the column in the incoming batch_row with the header == politician_full_name
    politician_name = batch_manager.retrieve_value_from_batch_row("politician_full_name", batch_header_map,
                                                                  one_batch_row)
    # Find the column in the incoming batch_row with the header == ctcl_uuid
    ctcl_uuid = batch_manager.retrieve_value_from_batch_row("politician_ctcl_uuid", batch_header_map, one_batch_row)
    politician_twitter_url = batch_manager.retrieve_value_from_batch_row("politician_twitter_url", batch_header_map,
                                                                         one_batch_row)
    facebook_id = batch_manager.retrieve_value_from_batch_row("politician_facebook_id", batch_header_map, one_batch_row)
    party_name = batch_manager.retrieve_value_from_batch_row("politician_party_name", batch_header_map, one_batch_row)
    first_name = batch_manager.retrieve_value_from_batch_row("politician_first_name", batch_header_map, one_batch_row)
    middle_name = batch_manager.retrieve_value_from_batch_row("politician_middle_name", batch_header_map, one_batch_row)
    last_name = batch_manager.retrieve_value_from_batch_row("politician_last_name", batch_header_map, one_batch_row)
    website_url = batch_manager.retrieve_value_from_batch_row("politician_website_url", batch_header_map, one_batch_row)
    email_address = batch_manager.retrieve_value_from_batch_row("politician_email_address", batch_header_map,
                                                                one_batch_row)
    youtube_id = batch_manager.retrieve_value_from_batch_row("politician_youtube_id", batch_header_map, one_batch_row)
    googleplus_id = batch_manager.retrieve_value_from_batch_row("politician_googleplus_id", batch_header_map,
                                                                one_batch_row)
    phone_number = batch_manager.retrieve_value_from_batch_row("politician_phone_number", batch_header_map,
                                                               one_batch_row)

    # extract twitter handle from politician_twitter_url
    politician_twitter_handle = extract_twitter_handle_from_text_string(politician_twitter_url)

    kind_of_action = 'TBD'
    single_politician_found = False
    multiple_politicians_found = False
    # First look up Politician table to see if an entry exists based on twitter_handle
    if positive_value_exists(politician_twitter_handle):
        try:
            politician_query = Politician.objects.all()
            politician_query = politician_query.filter(politician_twitter_handle__iexact=politician_twitter_handle)

            politician_item_list = list(politician_query)
            if len(politician_item_list):
                # entry exists
                batch_row_action_politician_status = 'BATCH_ROW_ACTION_POLITICIAN_RETRIEVED'
                batch_row_action_found = True
                new_action_politician_created = False
                # success = True
                # if a single entry matches, update that entry
                if len(politician_item_list) == 1:
                    kind_of_action = 'ADD_TO_EXISTING'
                    single_politician_found = True
                else:
                    # more than one entry found with a match in Politician
                    kind_of_action = 'DO_NOT_PROCESS'
                    multiple_politicians_found = True
            else:
                # kind_of_action = 'CREATE'
                single_politician_found = False
        except Politician.DoesNotExist:
            batch_row_action_politician = BatchRowActionPolitician()
            batch_row_action_found = False
            # success = True
            batch_row_action_politician_status = "BATCH_ROW_ACTION_POLITICIAN_NOT_FOUND"
            kind_of_action = 'TBD'
    # twitter handle does not exist, next look up politician based on politician_name
    if not single_politician_found and not multiple_politicians_found and positive_value_exists(politician_name):
        try:
            politician_query = Politician.objects.all()
            politician_query = politician_query.filter(politician_name__iexact=politician_name)

            politician_item_list = list(politician_query)
            if len(politician_item_list):
                # entry exists
                batch_row_action_politician_status = 'BATCH_ROW_ACTION_POLITICIAN_RETRIEVED'
                batch_row_action_found = True
                new_action_politician_created = False
                # success = True
                # if a single entry matches, update that entry
                if len(politician_item_list) == 1:
                    single_politician_found = True
                    kind_of_action = 'ADD_TO_EXISTING'
                else:
                    # more than one entry found with a match in Politician
                    kind_of_action = 'DO_NOT_PROCESS'
                    multiple_politicians_found = True
            else:
                single_politician_found = False
        except Politician.DoesNotExist:
            batch_row_action_politician = BatchRowActionPolitician()
            single_politician_found = True
            batch_row_action_found = False
            # success = True
            batch_row_action_politician_status = "BATCH_ROW_ACTION_POLITICIAN_NOT_FOUND"
            kind_of_action = 'TBD'
    if not positive_value_exists(politician_name) and not positive_value_exists(politician_twitter_handle):
        kind_of_action = 'TBD'
        batch_row_action_politician_status = "INSUFFICIENT_DATA_FOR_BATCH_ROW_ACTION_POLITICIAN_CREATE"
    if not single_politician_found and not multiple_politicians_found:
        kind_of_action = 'CREATE'
    # Create a new entry in BatchRowActionPolitician
    try:
        updated_values = {
            'politician_name': politician_name,
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'political_party': party_name,
            'ctcl_uuid': ctcl_uuid,
            'politician_email_address': email_address,
            'politician_phone_number': phone_number,
            'politician_twitter_handle': politician_twitter_handle,
            'politician_facebook_id': facebook_id,
            'politician_googleplus_id': googleplus_id,
            'politician_youtube_id': youtube_id,
            'politician_url': website_url,
            'kind_of_action': kind_of_action,
            'status': batch_row_action_politician_status
        }

        batch_row_action_politician, new_action_politician_created = BatchRowActionPolitician.objects.update_or_create(
            batch_header_id=batch_description.batch_header_id, batch_row_id=one_batch_row.id, defaults=updated_values)
        # new_action_politician_created = True
        success = True
        status = "BATCH_ROW_ACTION_POLITICIAN_CREATED"

    except Exception as e:
        batch_row_action_politician = BatchRowActionPolitician()
        batch_row_action_found = False
        success = False
        new_action_politician_created = False
        status = "BATCH_ROW_ACTION_POLITICIAN_RETRIEVE_ERROR"
        handle_exception(e, logger=logger, exception_message=status)

    results = {
        'success': success,
        'status': status,
        'new_action_politician_created': new_action_politician_created,
        'batch_row_action_politician': batch_row_action_politician,
    }
    return results


def import_elected_office_entry(batch_header_id, batch_row_id, create_entry_flag=False, update_entry_flag=False):
    """
    Import batch_rows for elected office, CREATE or ADD_TO_EXISTING
    Process batch row entries in order to create or update ElectedOffice entries
    :param batch_header_id: 
    :param batch_row_id: 
    :param create_entry_flag: set to True for CREATE
    :param update_entry_flag: set to True for ADD_TO_EXISTING
    :return: 
    """
    success = False
    status = ""
    number_of_elected_offices_created = 0
    number_of_elected_offices_updated = 0
    kind_of_batch = ""
    new_elected_office = ''
    new_elected_office_created = False
    batch_row_action_list_found = False

    if not positive_value_exists(batch_header_id):
        status = "IMPORT_ELECTED_OFFICE_ENTRY-BATCH_HEADER_ID_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    try:
        batch_description = BatchDescription.objects.get(batch_header_id=batch_header_id)
        batch_description_found = True
    except BatchDescription.DoesNotExist:
        # This is fine
        batch_description = BatchDescription()
        batch_description_found = False

    if not batch_description_found:
        status += "IMPORT_ELECTED_OFFICE_ENTRY-BATCH_DESCRIPTION_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

        # kind_of_batch = batch_description.kind_of_batch

    try:
        batch_header_map = BatchHeaderMap.objects.get(batch_header_id=batch_header_id)
        batch_header_map_found = True
    except BatchHeaderMap.DoesNotExist:
        # This is fine
        batch_header_map = BatchHeaderMap()
        batch_header_map_found = False

    if not batch_header_map_found:
        status += "CREATE_BATCH_ROW_ACTIONS-BATCH_HEADER_MAP_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    batch_row_list_found = False
    try:
        batch_row_action_list = BatchRowActionElectedOffice.objects.all()
        batch_row_action_list = batch_row_action_list.filter(batch_header_id=batch_header_id)
        if positive_value_exists(batch_row_id):
            batch_row_action_list = batch_row_action_list.filter(batch_row_id=batch_row_id)
        elif positive_value_exists(create_entry_flag):
            batch_row_action_list = batch_row_action_list.filter(kind_of_action=CREATE)
            kind_of_action = CREATE
        elif positive_value_exists(update_entry_flag):
            batch_row_action_list = batch_row_action_list.filter(kind_of_action=ADD_TO_EXISTING)
            kind_of_action = ADD_TO_EXISTING
        else:
            # error handling
            status += "IMPORT_BATCH_ROW_ACTIONS-KIND_OF_ACTION_MISSING"
            results = {
                'success':                              success,
                'status':                               status,
                'number_of_elected_offices_created':    number_of_elected_offices_created,
                'number_of_elected_offices_updated':    number_of_elected_offices_updated
            }
            return results

        if len(batch_row_action_list):
            batch_row_action_list_found = True

    except BatchDescription.DoesNotExist:
        batch_row_action_list = []
        batch_row_action_list_found = False
        pass

    # batch_manager = BatchManager()

    if not batch_row_action_list_found:
        status += "IMPORT_BATCH_ROW_ACTIONS-BATCH_ROW_ACTION_LIST_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    for one_batch_action_row in batch_row_action_list:

        # Find the column in the incoming batch_row with the header == elected_office_name
        elected_office_name = one_batch_action_row.elected_office_name
        google_civic_election_id = str(batch_description.google_civic_election_id)
        ctcl_uuid = one_batch_action_row.ctcl_uuid
        elected_office_description = one_batch_action_row.elected_office_description
        elected_office_is_partisan = one_batch_action_row.elected_office_is_partisan
        state_code = one_batch_action_row.state_code

        # Look up ElectedOffice to see if an entry exists
        # These five parameters are needed to look up in ElectedOffice table for a match
        if positive_value_exists(elected_office_name) and positive_value_exists(state_code) and \
                positive_value_exists(google_civic_election_id):
            elected_office_manager = ElectedOfficeManager()
            if create_entry_flag:
                results = elected_office_manager.create_elected_office_row_entry(elected_office_name, state_code,
                                                                                 elected_office_description,
                                                                                 ctcl_uuid,
                                                                                 elected_office_is_partisan,
                                                                                 google_civic_election_id)
                if results['new_elected_office_created']:
                    number_of_elected_offices_created += 1
                    success = True
                    # now update BatchRowActionElectedOffice table entry
                    try:
                        one_batch_action_row.kind_of_action = 'ADD_TO_EXISTING'
                        new_elected_office = results['new_elected_office']
                        one_batch_action_row.elected_office_we_vote_id = new_elected_office.we_vote_id
                        one_batch_action_row.save()
                    except Exception as e:
                        success = False
                        status += "ELECTED_OFFICE_RETRIEVE_ERROR"
                        handle_exception(e, logger=logger, exception_message=status)
            elif update_entry_flag:
                elected_office_we_vote_id = one_batch_action_row.elected_office_we_vote_id
                results = elected_office_manager.update_elected_office_row_entry(elected_office_name, state_code,
                                                                                 elected_office_description,
                                                                                 ctcl_uuid,
                                                                                 elected_office_is_partisan,
                                                                                 google_civic_election_id,
                                                                                 elected_office_we_vote_id)
                if results['elected_office_updated']:
                    number_of_elected_offices_updated += 1
                    success = True
            else:
                # This is error, it shouldn't reach here, we are handling CREATE or UPDATE entries only.
                status += "IMPORT_ELECTED_OFFICE_ENTRY:NO_CREATE_OR_UPDATE_ERROR"
                results = {
                    'success': success,
                    'status': status,
                    'number_of_elected_offices_created': number_of_elected_offices_created,
                    'number_of_elected_offices_updated': number_of_elected_offices_updated,
                    'new_elected_office': new_elected_office,
                }
                return results

    if number_of_elected_offices_created:
        status += "IMPORT_ELECTED_OFFICE_ENTRY:ELECTED_OFFICE_CREATED"
    elif number_of_elected_offices_updated:
        status += "IMPORT_ELECTED_OFFICE_ENTRY:ELECTED_OFFICE_UPDATED"

    results = {
        'success':                              success,
        'status':                               status,
        'number_of_elected_offices_created':    number_of_elected_offices_created,
        'number_of_elected_offices_updated':    number_of_elected_offices_updated,
        'new_elected_office':                   new_elected_office,
    }
    return results


def import_create_or_update_elected_office_entry(batch_header_id, batch_row_id):
    """
    Either create or update ElectedOffice table entry with batch_row elected_office details 
    
    :param batch_header_id: 
    :param batch_row_id: 
    :return: 
    """
    success = False
    status = ""
    elected_office_updated = False
    new_elected_office_created = False
    new_elected_office = ''
    number_of_elected_offices_created = 0
    number_of_elected_offices_updated = 0
    batch_row_action_list_found = False

    if not positive_value_exists(batch_header_id):
        status += "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY-BATCH_HEADER_ID_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    try:
        batch_description = BatchDescription.objects.get(batch_header_id=batch_header_id)
        batch_description_found = True
    except BatchDescription.DoesNotExist:
        # This is fine
        batch_description = BatchDescription()
        batch_description_found = False

    if not batch_description_found:
        status += "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY-BATCH_DESCRIPTION_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

        # kind_of_batch = batch_description.kind_of_batch

    try:
        batch_header_map = BatchHeaderMap.objects.get(batch_header_id=batch_header_id)
        batch_header_map_found = True
    except BatchHeaderMap.DoesNotExist:
        # This is fine
        batch_header_map = BatchHeaderMap()
        batch_header_map_found = False

    if not batch_header_map_found:
        status += "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY-BATCH_HEADER_MAP_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    batch_row_action_list_found = False
    try:
        batch_row_action_elected_office_list = BatchRowActionElectedOffice.objects.all()
        batch_row_action_elected_office_list = batch_row_action_elected_office_list.filter(
            batch_header_id=batch_header_id)
        if positive_value_exists(batch_row_id):
            batch_row_action_elected_office_list = batch_row_action_elected_office_list.filter(
                batch_row_id=batch_row_id)

        if len(batch_row_action_elected_office_list):
            batch_row_action_list_found = True
            # TODO assumption is that length of this list is going to be one, single record match
            batch_row_action_elected_office = batch_row_action_elected_office_list.first()
    except BatchDescription.DoesNotExist:
        # batch_row_action_list = []
        batch_row_action_list_found = False
        pass

    # batch_manager = BatchManager()

    if not batch_row_action_list_found:
        status += "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY-BATCH_ROW_ACTION_LIST_MISSING"
        results = {
            'success':                              success,
            'status':                               status,
            'number_of_elected_offices_created':    number_of_elected_offices_created,
            'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
        return results

    if batch_description_found and batch_header_map_found and batch_row_action_list_found:

        state_code = batch_row_action_elected_office.state_code
        elected_office_name = batch_row_action_elected_office.elected_office_name
        google_civic_election_id = str(batch_description.google_civic_election_id)
        ctcl_uuid = batch_row_action_elected_office.ctcl_uuid
        elected_office_description = batch_row_action_elected_office.elected_office_description
        elected_office_is_partisan = batch_row_action_elected_office.elected_office_is_partisan

        # Look up ElectedOffice to see if an entry exists

        kind_of_action = batch_row_action_elected_office.kind_of_action
        # Only add entries with kind_of_action set to either CREATE or ADD_TO_EXISTING.
        elected_office_manager = ElectedOfficeManager()
        if kind_of_action == 'CREATE':
            # call create_elected_office_row_entry
            results = elected_office_manager.create_elected_office_row_entry(elected_office_name, state_code,
                                                                             elected_office_description, ctcl_uuid,
                                                                             elected_office_is_partisan,
                                                                             google_civic_election_id)

            if results['new_elected_office_created']:
                success = True
                number_of_elected_offices_created += 1

                # now update BatchRowActionElectedOffice table entry
                try:
                    batch_row_action_elected_office.kind_of_action = ADD_TO_EXISTING
                    batch_row_action_elected_office.elected_office_we_vote_id = \
                        results['new_elected_office'].we_vote_id
                    batch_row_action_elected_office.save()
                except Exception as e:
                    success = False
                    new_elected_office_created = False
                    status += "IMPORT_UPDATE_OR_CREATE_ELECTED_OFFICE_ENTRY_ELECTED_OFFICE_RETRIEVE_ERROR"
                    handle_exception(e, logger=logger, exception_message=status)
        elif kind_of_action == 'ADD_TO_EXISTING':
            # call update_elected_office_row_entry
            elected_office_we_vote_id = batch_row_action_elected_office.elected_office_we_vote_id
            results = elected_office_manager.update_elected_office_row_entry(elected_office_name, state_code,
                                                                             elected_office_description,
                                                                             ctcl_uuid,
                                                                             elected_office_is_partisan,
                                                                             google_civic_election_id,
                                                                             elected_office_we_vote_id)
            if results['elected_office_updated']:
                success = True
                elected_office_updated = True
                number_of_elected_offices_updated += 1

            try:
                # store elected_we_vote_id from ElectedOffice table
                updated_elected_office = results['updated_elected_office']
                batch_row_action_elected_office.elected_office_we_vote_id = updated_elected_office.we_vote_id
                batch_row_action_elected_office.save()
            except Exception as e:
                success = False
                new_elected_office_created = False
                status += "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY_ELECTED_OFFICE_RETRIEVE_ERROR"
                handle_exception(e, logger=logger, exception_message=status)
        else:
            # kind_of_action is either TBD or DO_NOT_PROCESS, do nothing
            success = True
            status = "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY:ACTION_TBD_OR_DO_NOT_PROCESS"
    if number_of_elected_offices_created:
        status = "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY_ELECTED_OFFICE_CREATED"
    elif number_of_elected_offices_updated:
        status = "IMPORT_CREATE_OR_UPDATE_ELECTED_OFFICE_ENTRY_ELECTED_OFFICE_UPDATED"
    results = {
        'success':                              success,
        'status':                               status,
        'new_elected_office_created':           new_elected_office_created,
        'elected_office_updated':               elected_office_updated,
        'new_elected_office':                   new_elected_office,
        'number_of_elected_offices_created':    number_of_elected_offices_created,
        'number_of_elected_offices_updated':    number_of_elected_offices_updated
        }
    return results


def import_batch_action_rows(batch_header_id, kind_of_batch, kind_of_action):
    """
    Import batch action rows to master table, action is either CREATE or ADD_TO_EXISTING
    :param batch_header_id: 
    :param kind_of_batch: 
    :param kind_of_action: 
    :return: 
    """

    success = False
    status = ''
    number_of_elected_offices_created = 0
    number_of_elected_offices_updated = 0
    create_flag = False
    update_flag = False

    # for one_batch_row in batch_row_list:
    if kind_of_batch == 'ELECTED_OFFICE':
        if kind_of_action == 'CREATE':
            create_flag = True
        elif kind_of_action == 'ADD_TO_EXISTING':
            update_flag = True
        else:
            # this is error
            status = 'IMPORT_ROWS_ELECTED_OFFICE_INCORRECT_ACTION'
            results = {
                'success': success,
                'status': status,
                'batch_header_id': batch_header_id,
                'kind_of_batch': kind_of_batch,
                'table_rows_created': success,
                'number_of_table_rows_created': number_of_elected_offices_created,
                'number_of_table_rows_updated': number_of_elected_offices_updated
            }
            return results

        results = import_elected_office_entry(batch_header_id, 0, create_flag, update_flag)
        if results['success']:
            if results['number_of_elected_offices_created']:
                # for now, do not handle batch_row_action_elected_office data
                # batch_row_action_elected_office = results['batch_row_action_elected_office']
                number_of_elected_offices_created = results['number_of_elected_offices_created']
            elif results['number_of_elected_offices_updated']:
                number_of_elected_offices_updated = results['number_of_elected_offices_updated']
            success = True
    results = {
        'success': success,
        'status': status,
        'batch_header_id': batch_header_id,
        'kind_of_batch': kind_of_batch,
        'table_rows_created': success,
        'number_of_table_rows_created': number_of_elected_offices_created,
        'number_of_table_rows_updated': number_of_elected_offices_updated
    }
    return results
