# issue/views_admin.py
# Brought to you by We Vote. Be good.
# -*- coding: UTF-8 -*-

from .controllers import issues_import_from_master_server
from .models import Issue, IssueListManager, IssueManager
from admin_tools.views import redirect_to_sign_in_page
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.shortcuts import render
from exception.models import handle_record_found_more_than_one_exception,\
    handle_record_not_found_exception, handle_record_not_saved_exception, print_to_log
from position.models import PositionEntered, PositionListManager
from voter.models import voter_has_authority
import wevote_functions.admin
from wevote_functions.functions import convert_to_int, positive_value_exists
from django.http import HttpResponse
import json


logger = wevote_functions.admin.get_logger(__name__)


# This page does not need to be protected.
def issues_sync_out_view(request):
    issue_search = request.GET.get('issue_search', '')

    try:
        issue_list = Issue.objects.all()
        filters = []
        if positive_value_exists(issue_search):
            new_filter = Q(issue_name__icontains=issue_search)
            filters.append(new_filter)

            new_filter = Q(issue_description__icontains=issue_search)
            filters.append(new_filter)

            new_filter = Q(we_vote_id__icontains=issue_search)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                issue_list = issue_list.filter(final_filters)

        issue_list_dict = issue_list.values('we_vote_id', 'issue_name', 'issue_description')
        if issue_list_dict:
            issue_list_json = list(issue_list_dict)
            return HttpResponse(json.dumps(issue_list_json), content_type='application/json')
    except Exception as e:
        pass

    json_data = {
        'success': False,
        'status': 'ISSUES_LIST_MISSING'
    }
    return HttpResponse(json.dumps(json_data), content_type='application/json')


@login_required
def issues_import_from_master_server_view(request):
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    results = issues_import_from_master_server(request)

    if not results['success']:
        messages.add_message(request, messages.ERROR, results['status'])
    else:
        messages.add_message(request, messages.INFO, 'Issues import completed. '
                                                     'Saved: {saved}, Updated: {updated}, '
                                                     'Master data not imported (local duplicates found): '
                                                     '{duplicates_removed}, '
                                                     'Not processed: {not_processed}'
                                                     ''.format(saved=results['saved'],
                                                               updated=results['updated'],
                                                               duplicates_removed=results['duplicates_removed'],
                                                               not_processed=results['not_processed']))
    return HttpResponseRedirect(reverse('admin_tools:sync_dashboard', args=()) + "?google_civic_election_id=" +
                                str(google_civic_election_id) + "&state_code=" + str(state_code))


@login_required
def issue_list_view(request):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    issue_search = request.GET.get('issue_search', '')
    show_all = request.GET.get('show_all', False)

    issue_list = []
    issue_list_count = 0

    try:
        issue_list = Issue.objects.all()

        filters = []
        if positive_value_exists(issue_search):
            new_filter = Q(issue_name__icontains=issue_search)
            filters.append(new_filter)

            new_filter = Q(issue_description__icontains=issue_search)
            filters.append(new_filter)

            new_filter = Q(we_vote_id__icontains=issue_search)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                issue_list = issue_list.filter(final_filters)
        issue_list = issue_list.order_by('issue_name')
        issue_list_count = issue_list.count()

        if not positive_value_exists(show_all):
            issue_list = issue_list[:200]
    except Issue.DoesNotExist:
        # This is fine
        pass

    status_print_list = ""
    status_print_list += "issue_list_count: " + \
                         str(issue_list_count) + " "

    messages.add_message(request, messages.INFO, status_print_list)

    messages_on_stage = get_messages(request)

    template_values = {
        'messages_on_stage':        messages_on_stage,
        'issue_list':               issue_list,
        'issue_search':             issue_search,
        'google_civic_election_id': google_civic_election_id,
        'state_code':               state_code,
    }
    return render(request, 'issue/issue_list.html', template_values)


@login_required
def issue_new_view(request):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    # These variables are here because there was an error on the edit_process_view and the voter needs to try again
    issue_name = request.GET.get('issue_name', "")
    issue_description = request.GET.get('issue_description', "")

    # Its helpful to see existing issues when entering a new issue
    issue_list = []
    try:
        issue_list = Issue.objects.all()
        issue_list = issue_list.order_by('issue_name')[:500]
    except Issue.DoesNotExist:
        # This is fine
        pass

    messages_on_stage = get_messages(request)
    template_values = {
        'messages_on_stage':    messages_on_stage,
        'issue_list':           issue_list,
        'issue_name':           issue_name,
        'issue_description':    issue_description,
        'google_civic_election_id': google_civic_election_id,
        'state_code': state_code,
    }
    return render(request, 'issue/issue_edit.html', template_values)


@login_required
def issue_edit_view(request, issue_we_vote_id):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    # These variables are here because there was an error on the edit_process_view and the voter needs to try again
    issue_name = request.GET.get('issue_name', False)
    issue_description = request.GET.get('issue_description', False)

    messages_on_stage = get_messages(request)
    issue_on_stage_found = False
    issue_on_stage = Issue()

    try:
        issue_on_stage = Issue.objects.get(we_vote_id__iexact=issue_we_vote_id)
        issue_on_stage_found = True
    except Issue.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except Issue.DoesNotExist:
        # This is fine, create new below
        pass

    # Its helpful to see existing issues when entering a new issue
    issue_list = []
    try:
        issue_list = Issue.objects.all()
        issue_list = issue_list.order_by('issue_name')[:500]
    except Issue.DoesNotExist:
        # This is fine
        pass

    if issue_on_stage_found:
        pass

    template_values = {
        'messages_on_stage': messages_on_stage,
        'issue_list': issue_list,
        'issue': issue_on_stage,
        'issue_name': issue_name,
        'issue_description': issue_description,
        'google_civic_election_id': google_civic_election_id,
        'state_code': state_code,
    }

    return render(request, 'issue/issue_edit.html', template_values)


@login_required
def issue_edit_process_view(request):
    """
    Process the new or edit issue forms
    :param request:
    :return:
    """
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    issue_we_vote_id = request.POST.get('issue_we_vote_id', False)
    issue_name = request.POST.get('issue_name', False)
    issue_description = request.POST.get('issue_description', False)

    # Check to see if this issue is already being used anywhere
    issue_on_stage_found = False
    issue_on_stage = Issue()
    if positive_value_exists(issue_we_vote_id):
        try:
            issue_on_stage = Issue.objects.get(we_vote_id__iexact=issue_we_vote_id)
            issue_on_stage_found = True
        except Issue.MultipleObjectsReturned as e:
            handle_record_found_more_than_one_exception(e, logger=logger)
        except Issue.DoesNotExist:
            # This is fine, create new below
            pass

    if issue_on_stage_found:
        # Update
        if issue_name is not False:
            issue_on_stage.issue_name = issue_name
        if issue_description is not False:
            issue_on_stage.issue_description = issue_description

        issue_on_stage.save()

        messages.add_message(request, messages.INFO, 'Issue updated.')
    else:
        # Create new
        required_issue_variables = True if positive_value_exists(issue_name) else False
        if required_issue_variables:
            issue_on_stage = Issue(
                issue_name=issue_name,
                issue_description=issue_description,
            )
            if issue_description is not False:
                issue_on_stage.issue_description = issue_description

            issue_on_stage.save()
            issue_id = issue_on_stage.we_vote_id
            messages.add_message(request, messages.INFO, 'New issue saved.')
        else:
            messages.add_message(request, messages.INFO, 'Missing required variables.')

    url_variables = "?google_civic_election_id=" + str(google_civic_election_id) + \
                    "&state_code=" + str(state_code)

    if positive_value_exists(issue_we_vote_id):
        return HttpResponseRedirect(reverse('issue:issue_edit', args=(issue_we_vote_id,)) +
                                    url_variables)
    else:
        return HttpResponseRedirect(reverse('issue:issue_new', args=()) +
                                    url_variables)


@login_required
def issue_summary_view(request, issue_id):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    messages_on_stage = get_messages(request)
    issue_id = convert_to_int(issue_id)
    issue_on_stage_found = False
    issue_on_stage = Issue()
    try:
        issue_on_stage = Issue.objects.get(id=issue_id)
        issue_on_stage_found = True
    except Issue.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except Issue.DoesNotExist:
        # This is fine, create new
        pass

    if issue_on_stage_found:
        template_values = {
            'messages_on_stage': messages_on_stage,
            'issue': issue_on_stage,
        }
    else:
        template_values = {
            'messages_on_stage': messages_on_stage,
        }
    return render(request, 'issue/issue_summary.html', template_values)


@login_required
def issue_delete_process_view(request):
    """
    Delete this issue
    :param request:
    :return:
    """
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    issue_id = convert_to_int(request.GET.get('issue_id', 0))
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)

    # Retrieve this issue
    issue_on_stage_found = False
    issue_on_stage = Issue()
    if positive_value_exists(issue_id):
        try:
            issue_query = Issue.objects.filter(id=issue_id)
            if len(issue_query):
                issue_on_stage = issue_query[0]
                issue_on_stage_found = True
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not find issue -- exception.')

    if not issue_on_stage_found:
        messages.add_message(request, messages.ERROR, 'Could not find issue.')
        return HttpResponseRedirect(reverse('issue:issue_list', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id))

    # Are there any positions attached to this issue that should be moved to another
    # instance of this issue?
    position_list_manager = PositionListManager()
    retrieve_public_positions = True  # The alternate is positions for friends-only
    position_list = position_list_manager.retrieve_all_positions_for_issue_campaign(retrieve_public_positions, issue_id)
    if positive_value_exists(len(position_list)):
        positions_found_for_this_issue = True
    else:
        positions_found_for_this_issue = False

    try:
        if not positions_found_for_this_issue:
            # Delete the issue
            issue_on_stage.delete()
            messages.add_message(request, messages.INFO, 'Candidate Campaign deleted.')
        else:
            messages.add_message(request, messages.ERROR, 'Could not delete -- '
                                                          'positions still attached to this issue.')
            return HttpResponseRedirect(reverse('issue:issue_edit', args=(issue_id,)))
    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Could not delete issue -- exception.')
        return HttpResponseRedirect(reverse('issue:issue_edit', args=(issue_id,)))

    return HttpResponseRedirect(reverse('issue:issue_list', args=()) +
                                "?google_civic_election_id=" + str(google_civic_election_id))
