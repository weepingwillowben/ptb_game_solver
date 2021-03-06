from .agents import BaseAgent
from .populations import HomogenousPopulation
import numpy as np
import random
from .nash_finder import p1_solution, graph_opt_finder

class BasicGamesAgent(BaseAgent):
    '''
    agent wrapper for basic games Choices
    '''
    def __init__(self,my_choice):
        self.my_choice = my_choice

    def step(self,obs):
        return self.my_choice

    def __repr__(self):
        return "agent: {}".format(self.my_choice)

    __str__ = __repr__

class TaskEvalulator:
    def __init__(self,task,NUM_EVALS):
        self.task = task
        self.NUM_EVALS = NUM_EVALS
        self.reward = 0
        self.started_count = 0
        self.finished_count = 0

    def all_allocated(self):
        return self.started_count >= self.NUM_EVALS

    def is_finished(self):
        return self.finished_count >= self.NUM_EVALS

    def get_reward(self):
        assert self.is_finished()
        return self.reward / self.finished_count

    def inc_task(self):
        self.started_count += 1

    def place_eval(self,task,reward):
        assert task == self.task
        self.finished_count += 1
        self.reward += reward

class EvalAllocator:
    def __init__(self,NUM_EVALS):
        self.NUM_EVALS = NUM_EVALS
        self.task_list = []
        self.task_mapping = {}
        self.finish_task_index = 0
        self.started_task_index = 0

    def add_tasks(self,tasks):
        for task in tasks:
            self.task_mapping[task] = len(self.task_list)
            self.task_list.append(TaskEvalulator(task,self.NUM_EVALS))

    def all_finished(self):
        return len(self.task_list) <= self.finish_task_index

    def any_finished(self):
        return self.finish_task_index > 0

    def pop_finished(self):
        res = [(task.get_reward(),task.task) for task in self.task_list[:self.finish_task_index]]
        self.task_list = self.task_list[self.finish_task_index:]
        self.started_task_index -= self.finish_task_index
        self.finish_task_index = 0
        return res

    def place_eval(self,task,reward):
        assert task == self.task_list[self.finish_task_index].task
        self.task_list[self.finish_task_index].place_eval(task,reward)
        if self.task_list[self.finish_task_index].is_finished():
            self.finish_task_index += 1

    def next_task(self):
        idx = min(len(self.task_list)-1,self.started_task_index)
        task = self.task_list[self.started_task_index]
        task.inc_task()
        if task.all_allocated():
            self.started_task_index += 1
        return task.task


class PertLearner:
    def __init__(self,init_choice,NUM_PERTS,NUM_EVALS):
        self.main_choice = init_choice
        self.trained_stack = []
        self.NUM_PERTS = NUM_PERTS
        self.NUM_EVALS = NUM_EVALS
        self.eval_alloc = EvalAllocator(NUM_EVALS)
        self.init_perts()

    def init_perts(self):
        self.pert_agents = [self.main_choice.random_alt() for _ in range(self.NUM_PERTS)]
        self.pert_agents[0] = self.main_choice
        tasks = [(agent) for agent in range(self.NUM_PERTS)]
        self.eval_alloc.add_tasks(tasks)

    def evaluate_sample(self):
        return BasicGamesAgent(self.main_choice)

    def pop_trained_stack(self):
        trained_stack = self.trained_stack
        self.trained_stack = []
        return trained_stack

    def train_sample(self):
        # if need to set main to pert, do so and get next pert
        if self.eval_alloc.all_finished():
            task_list = self.eval_alloc.pop_finished()
            agent_reward = np.zeros(len(self.pert_agents))
            for rew,task in task_list:
                agent_reward[task] = rew
            self.main_choice = self.pert_agents[np.argmax(agent_reward)]
            self.trained_stack.append(self.main_choice)
            self.init_perts()

        task = self.eval_alloc.next_task()

        return self.pert_agents[task],task

    def experience_train(self,info,reward):
        self.eval_alloc.place_eval(info,reward)


class SelfPlayPertPopulation(HomogenousPopulation):
    def __init__(self,starter,NUM_PERTS=10,NUM_EVALS=10):
        self.main_agents = [starter]
        self.cur_learner = PertLearner(self.main_agent(),NUM_PERTS,NUM_EVALS)
        self.NUM_PERTS = NUM_PERTS
        self.NUM_EVALS = NUM_EVALS

    def main_agent(self):
        return self.main_agents[-1]

    def evaluate_sample(self):
        return BasicGamesAgent(self.main_agent())

    def train_sample(self):
        pert_sample,info = self.cur_learner.train_sample()
        self.main_agents += self.cur_learner.pop_trained_stack()
        return [BasicGamesAgent(self.main_agent()),BasicGamesAgent(pert_sample)],info

    def addExperiences(self,info,agents,result,observations,actions):
        learner_reward = -result
        self.cur_learner.experience_train(info,learner_reward)


class FictitiousPertPopulation(SelfPlayPertPopulation):
    def main_agent(self):
        return random.choice(self.main_agents)


class NashPertPopulation(HomogenousPopulation):
    def __init__(self,starter,NUM_PERTS=10,NUM_EVALS=10,POP_SIZE=10):
        self.current_pop = [starter.random_alt() for _ in range(POP_SIZE)]
        self.nash_support = np.ones(POP_SIZE)/POP_SIZE
        self.POP_SIZE = POP_SIZE
        self.NUM_EVALS = NUM_EVALS
        self.NUM_PERTS = NUM_PERTS
        self.eval_alloc = EvalAllocator(NUM_EVALS)
        self.eval_matrix = np.zeros([self.POP_SIZE,self.POP_SIZE])
        self.queue_matrix_evals()

    def queue_matrix_evals(self):
        tasks = [("matrix",(p1,p2))
                    for p1 in range(self.POP_SIZE)
                        for p2 in range(self.POP_SIZE)]

        self.eval_alloc.add_tasks(tasks)

    def queue_pop_evals(self):
        self.pop_alts = [[choice.random_alt() for _ in range(self.NUM_PERTS)] for choice in self.current_pop]
        for i in range(self.POP_SIZE):
            self.pop_alts[i][0] = self.current_pop[i]
        tasks = [("learn",(p,pert)) for p in range(self.POP_SIZE) for pert in range(self.NUM_PERTS)]
        self.eval_alloc.add_tasks(tasks)

    def recalc_nash(self):
        self.nash_support = p1_solution(self.eval_matrix)

    def nash_sample(self):
        return BasicGamesAgent(random.choices(self.current_pop,weights=self.nash_support)[0])

    def evaluate_sample(self):
        return BasicGamesAgent(random.choice(self.current_pop))

    def handle_task_completion(self):
        if self.eval_alloc.all_finished():
            tasks = self.eval_alloc.pop_finished()
            _,(t0name,_) = tasks[0]
            if t0name == "matrix":
                self.eval_matrix = np.zeros([self.POP_SIZE,self.POP_SIZE])
                for rew,task in tasks:
                    name,data = task
                    assert name == t0name
                    p1,p2 = data
                    self.eval_matrix[p1][p2] = rew
                self.recalc_nash()
                self.queue_pop_evals()
            elif t0name == "learn":
                pop_values = [[0 for _ in range(self.NUM_PERTS)] for choice in self.current_pop]
                for rew,task in tasks:
                    name,data = task
                    assert name == t0name
                    p1,pert = data
                    pop_values[p1][pert] += rew
                for i in range(self.POP_SIZE):
                    self.current_pop[i] = self.pop_alts[i][np.argmax(pop_values[i])]

                self.queue_matrix_evals()
            else:
                assert False, t0name

    def train_sample(self):
        name,data = task = self.eval_alloc.next_task()
        if name == "matrix":
            p1,p2 = data
            return [BasicGamesAgent(self.current_pop[p1]),BasicGamesAgent(self.current_pop[p2])],task
        else:
            p1,pert = data
            return [BasicGamesAgent(self.pop_alts[p1][pert]),self.pop_alt_compare(p1)],task

    def pop_alt_compare(self,pop_alt_idx):
        return self.nash_sample()

    def addExperiences(self,info,agents,result,observations,actions):
        self.eval_alloc.place_eval(info,result)
        self.handle_task_completion()

class RectifiedNashPertPop(NashPertPopulation):
    def pop_alt_compare(self,pop_alt_idx):
        win_val = np.maximum(0,self.eval_matrix[pop_alt_idx])
        support_val = self.nash_support
        target_mag = win_val * support_val
        sum_mag = np.sum(target_mag)
        target_mag = target_mag/sum_mag if sum_mag > 0 else self.nash_support
        compare_choice = random.choices(self.current_pop,weights=target_mag)[0]
        return BasicGamesAgent(compare_choice)

class SoftPertPop(NashPertPopulation):
    '''
    The idea behind soft solvers is to replace the strict evaluations of the
    nash based solvers with estiated values and resplace the techniques with
    techniques that are more suited towards using these estimated values.

    In particular, the matrix of reward payoffs has a row for each agent

    [r1,r2,r3,...,rn]
    Now, each agent in this reward vector also has an overall strength,
    and you have a strength relative to your opponent's overall strength that indicates
    your counter value.

    Finally, you can use these rescaled values compared to the other values in your reward list

    in particular, you have:

    Uniform: weighted uniformly
    Nash: weighted by how well you do
    Rectfified nash: weighted by your rescaled value (i.e. how well you do compared to others)

    However, there is a lot more you can do.

    You can consider errors in the reward matrix, and train based off UCB or Expected improvement.

    You can look at rate of change of evaluations.

    A delta matrix
    [d1,d2,...,dn]
    for the change in r over time. This will have high error, so need to watch that.

    But the delta vector is also informative. You can train against agents you
    have relatively high delta against.

    Nash is a not ideal measure of overall strength, because it is poorly regularized

    A better way is to regularize it like this:

    p^T A p + c |p|^2

    With many agents or heterogenous agents, you want a matching scheme:

    a_i matches with b_j to the degree that b_j is better for a_i relative to other bs.

    Gives a bipartite (or n-partite in general case) graph of different agents with weights pointing to each other:

    Restrictions: flow in to node equals flow out (equals 1?)
    Regulaized: high flow edges are penalized
    Objective: maximizes reward for source agent.
    '''
    def __init__(self,starter,REG_VAL=0.03,NUM_PERTS=10,NUM_EVALS=10,POP_SIZE=10):
        super().__init__(starter,NUM_PERTS,NUM_EVALS,POP_SIZE)
        self.REG_VAL = REG_VAL

    def recalc_nash(self):
        self.nash_support = np.ones(self.POP_SIZE)/self.POP_SIZE
        self.response_mat = graph_opt_finder(self.eval_matrix,self.REG_VAL)

    def pop_alt_compare(self,pop_alt_idx):
        response_probs = self.response_mat[pop_alt_idx]
        compare_choice = random.choices(self.current_pop,weights=response_probs)[0]
        return BasicGamesAgent(compare_choice)
