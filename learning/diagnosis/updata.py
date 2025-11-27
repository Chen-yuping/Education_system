#首先在view中的take_exercise中，如果做了一个题目，我们就调用update_knowledge_mastery(request.user, exercise, answer_log.is_correct)，
#在update_knowledge_mastery我们要实现增加或修改知识点掌握程度

# student = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="学生")
# exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, verbose_name="习题")
# selected_choices = models.ManyToManyField(Choice, blank=True, verbose_name="选择的选项")
# text_answer = models.TextField(blank=True, verbose_name="文本答案")
# is_correct = models.BooleanField(null=True, verbose_name="是否正确")
# time_spent = models.IntegerField(default=0, verbose_name="答题耗时(秒)")
# submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")


def knowledge_mastery_diagnoses(user, answerlog):

    return