import string

import pyparsing
import pyparsing as pp
from pyparsing import original_text_for


class Prompt():

    def __init__(self, parts: list):
        for c in parts:
            if type(c) is not Attention and not issubclass(type(c), BaseFragment):
                raise PromptParser.ParsingException(f"Prompt cannot contain {type(c)}, only {BaseFragment.__subclasses__()} are allowed")
        self.children = parts
    def __repr__(self):
        return f"Prompt:{self.children}"
    def __eq__(self, other):
        return type(other) is Prompt and other.children == self.children

class FlattenedPrompt():
    def __init__(self, parts: list):
        # verify type correctness
        parts_converted = []
        for part in parts:
            if issubclass(type(part), BaseFragment):
                parts_converted.append(part)
            elif type(part) is tuple:
                # upgrade tuples to Fragments
                if type(part[0]) is not str or (type(part[1]) is not float and type(part[1]) is not int):
                    raise PromptParser.ParsingException(
                        f"FlattenedPrompt cannot contain {part}, only Fragments or (str, float) tuples are allowed")
                parts_converted.append(Fragment(part[0], part[1]))
            else:
                raise PromptParser.ParsingException(
                    f"FlattenedPrompt cannot contain {part}, only Fragments or (str, float) tuples are allowed")
        # all looks good
        self.children = parts_converted

    def __repr__(self):
        return f"FlattenedPrompt:{self.children}"
    def __eq__(self, other):
        return type(other) is FlattenedPrompt and other.children == self.children

# abstract base class for Fragments
class BaseFragment:
    pass

class Fragment(BaseFragment):
    def __init__(self, text: str, weight: float=1):
        assert(type(text) is str)
        self.text = text
        self.weight = float(weight)

    def __repr__(self):
        return "Fragment:'"+self.text+"'@"+str(self.weight)
    def __eq__(self, other):
        return type(other) is Fragment \
            and other.text == self.text \
            and other.weight == self.weight

class Attention():
    def __init__(self, weight: float, children: list):
        self.weight = weight
        self.children = children
        #print(f"A: requested attention '{children}' to {weight}")

    def __repr__(self):
        return f"Attention:'{self.children}' @ {self.weight}"
    def __eq__(self, other):
        return type(other) is Attention and other.weight == self.weight and other.fragment == self.fragment

class CrossAttentionControlledFragment(BaseFragment):
    pass

class CrossAttentionControlSubstitute(CrossAttentionControlledFragment):
    def __init__(self, original: Fragment, edited: Fragment):
        self.original = original
        self.edited = edited

    def __repr__(self):
        return f"CrossAttentionControlSubstitute:({self.original}->{self.edited})"
    def __eq__(self, other):
        return type(other) is CrossAttentionControlSubstitute \
               and other.original == self.original \
               and other.edited == self.edited

class CrossAttentionControlAppend(CrossAttentionControlledFragment):
    def __init__(self, fragment: Fragment):
        self.fragment = fragment
    def __repr__(self):
        return "CrossAttentionControlAppend:",self.fragment
    def __eq__(self, other):
        return type(other) is CrossAttentionControlAppend \
               and other.fragment == self.fragment



class Conjunction():
    def __init__(self, prompts: list, weights: list = None):
        # force everything to be a Prompt
        #print("making conjunction with", parts)
        self.prompts = [x if (type(x) is Prompt
                          or type(x) is Blend
                          or type(x) is FlattenedPrompt)
                      else Prompt(x) for x in prompts]
        self.weights = [1.0]*len(self.prompts) if weights is None else list(weights)
        if len(self.weights) != len(self.prompts):
            raise PromptParser.ParsingException(f"while parsing Conjunction: mismatched parts/weights counts {prompts}, {weights}")
        self.type = 'AND'

    def __repr__(self):
        return f"Conjunction:{self.prompts} | weights {self.weights}"
    def __eq__(self, other):
        return type(other) is Conjunction \
               and other.prompts == self.prompts \
               and other.weights == self.weights


class Blend():
    def __init__(self, prompts: list, weights: list[float], normalize_weights: bool=True):
        #print("making Blend with prompts", prompts, "and weights", weights)
        if len(prompts) != len(weights):
            raise PromptParser.ParsingException(f"while parsing Blend: mismatched prompts/weights counts {prompts}, {weights}")
        for c in prompts:
            if type(c) is not Prompt and type(c) is not FlattenedPrompt:
                raise(PromptParser.ParsingException(f"{type(c)} cannot be added to a Blend, only Prompts or FlattenedPrompts"))
        # upcast all lists to Prompt objects
        self.prompts = [x if (type(x) is Prompt or type(x) is FlattenedPrompt)
                         else Prompt(x) for x in prompts]
        self.prompts = prompts
        self.weights = weights
        self.normalize_weights = normalize_weights

    def __repr__(self):
        return f"Blend:{self.prompts} | weights {self.weights}"
    def __eq__(self, other):
        return other.__repr__() == self.__repr__()


class PromptParser():

    class ParsingException(Exception):
        pass

    def __init__(self, attention_plus_base=1.1, attention_minus_base=0.9):

        self.attention_plus_base = attention_plus_base
        self.attention_minus_base = attention_minus_base

        self.root = self.build_parser_logic()


    def parse(self, prompt: str) -> Conjunction:
        '''
        :param prompt: The prompt string to parse
        :return: a tuple
        '''
        #print(f"!!parsing '{prompt}'")

        if len(prompt.strip()) == 0:
            return Conjunction(prompts=[FlattenedPrompt([('', 1.0)])], weights=[1.0])

        root = self.root.parse_string(prompt)
        #print(f"'{prompt}' parsed to root", root)
        #fused = fuse_fragments(parts)
        #print("fused to", fused)

        return self.flatten(root[0])

    def flatten(self, root: Conjunction):

        print("flattening", root)

        def fuse_fragments(items):
            # print("fusing fragments in ", items)
            result = []
            for x in items:
                if type(x) is CrossAttentionControlSubstitute:
                    original_fused = fuse_fragments(x.original)
                    edited_fused = fuse_fragments(x.edited)
                    result.append(CrossAttentionControlSubstitute(original_fused, edited_fused))
                else:
                    last_weight = result[-1].weight \
                        if (len(result) > 0 and not issubclass(type(result[-1]), CrossAttentionControlledFragment)) \
                        else None
                    this_text = x.text
                    this_weight = x.weight
                    if last_weight is not None and last_weight == this_weight:
                        last_text = result[-1].text
                        result[-1] = Fragment(last_text + ' ' + this_text, last_weight)
                    else:
                        result.append(x)
            return result

        def flatten_internal(node, weight_scale, results, prefix):
            #print(prefix + "flattening", node, "...")
            if type(node) is pp.ParseResults:
                for x in node:
                    results = flatten_internal(x, weight_scale, results, prefix+'pr')
                #print(prefix, " ParseResults expanded, results is now", results)
            elif type(node) is Attention:
                # if node.weight < 1:
                # todo: inject a blend when flattening attention with weight <1"
                for c in node.children:
                    results = flatten_internal(c, weight_scale * node.weight, results, prefix + '  ')
            elif type(node) is Fragment:
                results += [Fragment(node.text, node.weight*weight_scale)]
            elif type(node) is CrossAttentionControlSubstitute:
                original = flatten_internal(node.original, weight_scale, [], prefix + ' CAo ')
                edited = flatten_internal(node.edited, weight_scale, [], prefix + ' CAe ')
                results += [CrossAttentionControlSubstitute(original, edited)]
            elif type(node) is Blend:
                flattened_subprompts = []
                #print(" flattening blend with prompts", node.prompts, "weights", node.weights)
                for prompt in node.prompts:
                    # prompt is a list
                    flattened_subprompts = flatten_internal(prompt, weight_scale, flattened_subprompts, prefix+'B ')
                results += [Blend(prompts=flattened_subprompts, weights=node.weights)]
            elif type(node) is Prompt:
                #print(prefix + "about to flatten Prompt with children", node.children)
                flattened_prompt = []
                for child in node.children:
                    flattened_prompt = flatten_internal(child, weight_scale, flattened_prompt, prefix+'P ')
                results += [FlattenedPrompt(parts=fuse_fragments(flattened_prompt))]
                #print(prefix + "after flattening Prompt, results is", results)
            else:
                raise PromptParser.ParsingException(f"unhandled node type {type(node)} when flattening {node}")
            print(prefix + "-> after flattening", type(node).__name__, "results is", results)
            return results


        flattened_parts = []
        for part in root.prompts:
            flattened_parts += flatten_internal(part, 1.0, [], ' C| ')
        weights = root.weights
        return Conjunction(flattened_parts, weights)



    def build_parser_logic(self):

        lparen = pp.Literal("(").suppress()
        rparen = pp.Literal(")").suppress()
        quotes = pp.Literal('"').suppress()

        # accepts int or float notation, always maps to float
        number = pyparsing.pyparsing_common.real | pp.Word(pp.nums).set_parse_action(pp.token_map(float))
        SPACE_CHARS = string.whitespace

        attention = pp.Forward()

        def make_fragment(x):
            #print("### making fragment for", x)
            if type(x) is str:
                return Fragment(x)
            elif type(x) is pp.ParseResults or type(x) is list:
                #print(f'converting {x} to Fragment')
                return Fragment(' '.join([s for s in x]))
            else:
                raise PromptParser.ParsingException("Cannot make fragment from " + str(x))

        unquoted_fragment = pp.Forward()
        quoted_fragment = pp.Forward()
        parenthesized_fragment = pp.Forward()

        def parse_fragment_str(x):
            print("parsing", x)
            if len(x[0].strip()) == 0:
                return Fragment('')
            fragment_parser = pp.Group(pp.OneOrMore(attention | pp.Word(pp.printables, exclude_chars=string.whitespace).set_parse_action(make_fragment)))
            fragment_parser.set_name('word_or_attention')
            result = fragment_parser.parse_string(x[0])
            #result = (pp.OneOrMore(attention | unquoted_fragment) + pp.StringEnd()).parse_string(x[0])
            print("parsed to", result)
            return result

        quoted_fragment << pp.QuotedString(quote_char='"', esc_char='\\')
        quoted_fragment.set_parse_action(make_fragment).set_name('quoted_fragment')

        unquoted_fragment << pp.Combine(pp.OneOrMore(
            pp.Literal('\\"').set_debug(False) |
            pp.Literal('\\').set_debug(False) |
            pp.Word(pp.printables, exclude_chars=string.whitespace + '\\"')
        ))
        unquoted_fragment.set_parse_action(make_fragment).set_name('unquoted_fragment')

        parenthesized_fragment << pp.Or([
            (lparen + quoted_fragment.set_parse_action(parse_fragment_str).set_debug(True) + rparen).set_name('-quoted_paren_internal').set_debug(True),
            (lparen + rparen).set_parse_action(lambda x: make_fragment('')).set_name('-()').set_debug(True),
            (lparen + pp.Combine(pp.OneOrMore(
                pp.Literal('\\)').set_debug(False) |
                pp.Literal('\\').set_debug(False) |
                pp.Word(pp.printables, exclude_chars=string.whitespace + '\\)') |
                pp.Word(string.whitespace)
            )).set_name('--combined').set_parse_action(parse_fragment_str).set_debug(True) + rparen)]).set_name('-unquoted_paren_internal').set_debug(True)
        parenthesized_fragment.set_name('parenthesized_fragment').set_debug(True)

        # attention control of the form +(phrase) / -(phrase) / <weight>(phrase)
        # phrase can be multiple words, can have multiple +/- signs to increase the effect or type a floating point or integer weight
        attention_head = (number | pp.Word('+') | pp.Word('-'))\
            .set_name("attention_head")\
            .set_debug(False)
        fragment_inside_attention = pp.CharsNotIn(SPACE_CHARS+'()')\
            .set_parse_action(make_fragment)\
            .set_name("fragment_inside_attention")\
            .set_debug(False)
        attention_with_parens = pp.Forward()
        attention_with_parens_body = pp.nested_expr(content=pp.delimited_list((attention_with_parens | fragment_inside_attention), delim=SPACE_CHARS))
        attention_with_parens << (attention_head + attention_with_parens_body)

        def make_attention(x):
            # print("making Attention from parsing with args", x0, x1)
            weight = 1
            # number(str)
            if type(x[0]) is float or type(x[0]) is int:
                weight = float(x[0])
            # +(str) or -(str) or +str or -str
            elif type(x[0]) is str:
                base = self.attention_plus_base if x[0][0] == '+' else self.attention_minus_base
                weight = pow(base, len(x[0]))
            # print("Making attention with children of type", [str(type(x)) for x in x1])
            return Attention(weight=weight, children=x[1])

        attention_with_parens.set_parse_action(make_attention)\
            .set_name("attention_with_parens")\
            .set_debug(False)

        # attention control of the form ++word --word (no parens)
        attention_without_parens = (
                (pp.Word('+') | pp.Word('-')) +
                pp.CharsNotIn(SPACE_CHARS+'()').set_parse_action(lambda x: [[make_fragment(x)]])
            )\
            .set_name("attention_without_parens")\
            .set_debug(False)
        attention_without_parens.set_parse_action(make_attention)

        attention << (attention_with_parens | attention_without_parens)\
            .set_name("attention")\
            .set_debug(False)

        # cross-attention control
        empty_string = ((lparen + rparen) |
                        pp.Literal('""').suppress() |
                        (lparen + pp.Literal('""').suppress() + rparen)
                        ).set_parse_action(lambda x: Fragment(""))
        empty_string.set_name('empty_string')

        original_fragment = empty_string | quoted_fragment | parenthesized_fragment | unquoted_fragment
        edited_fragment = parenthesized_fragment
        cross_attention_substitute = original_fragment + pp.Literal(".swap").suppress() + edited_fragment

        cross_attention_substitute.set_name('cross_attention_substitute').set_debug(True)

        def make_cross_attention_substitute(x):
            print("making cacs for", x)
            cacs = CrossAttentionControlSubstitute(x[0], x[1])
            print("made", cacs)
            return cacs
        cross_attention_substitute.set_parse_action(make_cross_attention_substitute)

        # simple fragments of text
        prompt_part = (
                cross_attention_substitute
                | attention
                | quoted_fragment
                | unquoted_fragment
             )
        prompt_part.set_debug(False)
        prompt_part.set_name("prompt_part")

        empty = (
                (lparen + pp.ZeroOrMore(pp.Word(string.whitespace)) + rparen) |
                (quotes + pp.ZeroOrMore(pp.Word(string.whitespace)) + quotes)).set_debug(False).set_name('empty')

        # root prompt definition
        prompt = (pp.Group(pp.OneOrMore(prompt_part) | empty) + pp.StringEnd()) \
            .set_parse_action(lambda x: Prompt(x[0]))

        # weighted blend of prompts
        # ("promptA", "promptB").blend(a, b) where "promptA" and "promptB" are valid prompts and a and b are float or
        # int weights.
        # can specify more terms eg ("promptA", "promptB", "promptC").blend(a,b,c)

        def make_prompt_from_quoted_string(x):
            #print(' got quoted prompt', x)

            x_unquoted = x[0][1:-1]
            if len(x_unquoted.strip()) == 0:
                # print(' b : just an empty string')
                return Prompt([Fragment('')])
            # print(' b parsing ', c_unquoted)
            x_parsed = prompt.parse_string(x_unquoted)
            #print(" quoted prompt was parsed to", type(x_parsed),":", x_parsed)
            return x_parsed[0]

        quoted_prompt = pp.dbl_quoted_string.set_parse_action(make_prompt_from_quoted_string)
        quoted_prompt.set_name('quoted_prompt')

        blend_terms = pp.delimited_list(quoted_prompt).set_name('blend_terms')
        blend_weights = pp.delimited_list(number).set_name('blend_weights')
        blend = pp.Group(lparen + pp.Group(blend_terms) + rparen
                         + pp.Literal(".blend").suppress()
                         + lparen + pp.Group(blend_weights) + rparen).set_name('blend')
        blend.set_debug(False)


        blend.set_parse_action(lambda x: Blend(prompts=x[0][0], weights=x[0][1]))

        conjunction_terms = blend_terms.copy().set_name('conjunction_terms')
        conjunction_weights = blend_weights.copy().set_name('conjunction_weights')
        conjunction_with_parens_and_quotes = pp.Group(lparen + pp.Group(conjunction_terms) + rparen
                         + pp.Literal(".and").suppress()
                         + lparen + pp.Optional(pp.Group(conjunction_weights)) + rparen).set_name('conjunction')
        def make_conjunction(x):
            parts_raw = x[0][0]
            weights = x[0][1] if len(x[0])>1 else [1.0]*len(parts_raw)
            parts = [part for part in parts_raw]
            return Conjunction(parts, weights)
        conjunction_with_parens_and_quotes.set_parse_action(make_conjunction)

        implicit_conjunction = pp.OneOrMore(blend | prompt)
        implicit_conjunction.set_parse_action(lambda x: Conjunction(x))

        conjunction = conjunction_with_parens_and_quotes | implicit_conjunction
        conjunction.set_debug(False)

        # top-level is a conjunction of one or more blends or prompts
        return conjunction
