"""Audit history boundaries and visible, owner-checked student feedback."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import access,audit,feedback,pipeline
from phases.phase3_hard.storage import connect
from streamlit.testing.v1 import AppTest
from ui import chat

ADMIN = access.Principal('test-admin','admin')
USER = access.Principal('test-student','student')


class AdminFeedbackChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ,{'DOCUMIND_DATA_DIR':self.temp.name,
            'DOCUMIND_DB':str(Path(self.temp.name)/'documind.db')})
        env.start();self.addCleanup(env.stop)

    def seed(self,count):
        with connect() as db:
            audit._schema(db)
            db.executemany('INSERT INTO audit(ts,actor,event,details) VALUES (?,?,?,?)',
                [(number,'test-admin',f'event-{number}','{}') for number in range(count)])

    def test_older_pages_have_no_gaps_even_after_a_new_event(self):
        self.seed(251)
        first = audit.page(ADMIN)
        audit.record(ADMIN,'new-event')
        second = audit.page(ADMIN,1,through_id=first['through_id'])
        third = audit.page(ADMIN,2,through_id=first['through_id'])
        ids = [row['id'] for page in (first,second,third) for row in page['records']]
        self.assertEqual(ids,list(range(251,0,-1)))
        self.assertEqual(audit.page(ADMIN)['records'][0]['event'],'new-event')
        self.assertEqual(len(second['records']),100)
        self.assertEqual(len(third['records']),51)

    def test_export_count_is_independent_and_can_include_all_retained_logs(self):
        self.seed(20005)
        audit.record(ADMIN,'retention-check')
        self.assertEqual(audit.page(ADMIN)['total'],20000)
        self.assertEqual(len(audit.recent(ADMIN,200)),200)
        self.assertEqual(len(audit.recent(ADMIN,20000)),20000)
        self.assertEqual(len(audit.recent(ADMIN,99999)),20000)
        self.assertEqual(len(audit.page(ADMIN,99999)['records']),100)

    def test_empty_history_and_admin_permissions(self):
        self.assertEqual(audit.page(ADMIN)['records'],[])
        with self.assertRaises(PermissionError): audit.page(USER)
        with self.assertRaises(PermissionError): audit.recent(USER,20000)

    def test_admin_ui_paginates_refreshes_and_exports_requested_count(self):
        self.seed(251)
        app = AppTest.from_string('''
from core.access import Principal
from ui.admin_controls import audit_history
audit_history(Principal('test-admin','admin'))
''').run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.dataframe[0].value),100)
        next(button for button in app.button if button.label=='Next (older)').click().run()
        self.assertEqual(app.dataframe[0].value['event'].iloc[0],'event-150')
        self.assertEqual(app.session_state['audit_page'],1)
        import streamlit as st
        with patch.object(st,'download_button',wraps=st.download_button) as download:
            app.number_input[0].set_value(225).run()
            self.assertEqual(len(json.loads(download.call_args.args[1])),225)
        next(button for button in app.button if button.label=='Next (older)').click().run()
        self.assertEqual(len(app.dataframe[0].value),51)
        self.assertTrue(next(button for button in app.button if button.label=='Next (older)').disabled)
        next(button for button in app.button if button.label=='Previous (newer)').click().run()
        self.assertEqual(app.session_state['audit_page'],1)
        audit.record(ADMIN,'new-event')
        next(button for button in app.button if button.label=='Refresh logs').click().run()
        self.assertEqual(app.session_state['audit_page'],0)
        self.assertEqual(app.dataframe[0].value['event'].iloc[0],'new-event')

    def student_app(self):
        result = pipeline.QueryResult('Water is H2O.',[],'Water formula?',5,status='no_evidence')
        result.feedback_id = feedback.issue(USER,result)
        app = AppTest.from_string('''
from core.access import Principal
from ui.chat import render_chat
render_chat(Principal('test-student','student'))
''')
        return result,app

    def test_student_choices_are_visible_and_saved_for_each_answer(self):
        for vote in ('helpful','incorrect','missing_information'):
            result,app = self.student_app()
            with patch.object(chat,'query_student',return_value=result):
                app.run(timeout=30)
                app.chat_input[0].set_value('Water formula?').run(timeout=30)
                self.assertEqual(len(app.exception),0)
                self.assertEqual(len(app.expander),0)
                self.assertEqual(app.radio[0].options,['Helpful','Incorrect','Incomplete'])
                app.radio[0].set_value(vote)
                app.text_input[0].set_value('Please check the source. Contact person@example.com')
                next(button for button in app.button if button.label=='Send feedback').click().run()
                self.assertEqual(len(app.exception),0)
                row = feedback.recent(ADMIN)[0]
                self.assertEqual(row['vote'],vote)
                self.assertEqual(row['response_id'],result.feedback_id)
                self.assertNotIn('person@example.com',row['note'])
                self.assertTrue(any('Feedback saved:' in item.value for item in app.success))
                app.run()
                self.assertTrue(any('Feedback saved:' in item.value for item in app.success))

    def test_student_must_choose_a_vote_and_cannot_rate_another_account(self):
        result,app = self.student_app()
        with patch.object(chat,'query_student',return_value=result):
            app.run(timeout=30)
            app.chat_input[0].set_value('Water formula?').run(timeout=30)
            next(button for button in app.button if button.label=='Send feedback').click().run()
            self.assertEqual(feedback.recent(ADMIN),[])
            self.assertTrue(any('Choose Helpful' in warning.value for warning in app.warning))
        with self.assertRaises(PermissionError):
            feedback.submit(access.Principal('another-student','student'),result.feedback_id,'helpful')


if __name__=='__main__': unittest.main(verbosity=2)
