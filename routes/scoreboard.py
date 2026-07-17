import os

from fastapi import APIRouter, Request

import state
from web import display_config, redirect, render

router = APIRouter()


@router.get('/config')
def route_config():
    """Display config as JSON — for native clients (Qt TV) that render natively."""
    return display_config()


@router.get('/')
def route_index():
    return redirect('/live')


@router.get('/scoreboard')
def route_scoreboard_default(request: Request):
    lanes = int(state.settings.get('num_lanes', 8))
    return render(request, 'scoreboard.html',
                  meet_title=state.settings['meet_title'],
                  num_lanes=lanes,
                  nosplash='nosplash' in request.query_params,
                  test_background='test' in request.query_params)


@router.get('/live')
def route_live(request: Request):
    lanes = int(state.settings.get('num_lanes', 8))
    carousel_images = sorted(
        f for f in os.listdir(state.IMAGES_DIR)
        if os.path.isfile(os.path.join(state.IMAGES_DIR, f))
    )
    return render(request, 'live.html',
                  meet_title=state.settings['meet_title'],
                  num_lanes=lanes,
                  nosplash='nosplash' in request.query_params,
                  test_background='test' in request.query_params,
                  carousel_images=carousel_images,
                  carousel_interval=int(state.settings.get('carousel_interval', 10)),
                  theme_fonts={**state.DEFAULT_THEME_FONTS,
                               **state.settings.get('theme_fonts', {})})


@router.get('/live-mobile')
def route_live_mobile(request: Request):
    lanes = int(state.settings.get('num_lanes', 8))
    carousel_images = sorted(
        f for f in os.listdir(state.IMAGES_DIR)
        if os.path.isfile(os.path.join(state.IMAGES_DIR, f))
    )
    return render(request, 'live-mobile.html',
                  meet_title=state.settings['meet_title'],
                  num_lanes=lanes,
                  carousel_images=carousel_images,
                  carousel_interval=int(state.settings.get('carousel_interval', 10)),
                  theme_fonts={**state.DEFAULT_THEME_FONTS,
                               **state.settings.get('theme_fonts', {})})


@router.get('/mobile')
def route_mobile(request: Request):
    app_title = (state.settings.get('app_window_title') or
                 state.settings.get('meet_title') or 'Tremplin')
    return render(request, 'mobile.html', t=state._mobile_strings(),
                  app_title=app_title)


@router.get('/results')
def route_results(request: Request):
    return render(request, 'results.html',
                  num_lanes=int(state.settings.get('num_lanes', 8)),
                  theme_colors={**state.DEFAULT_THEME_COLORS,
                                **state.settings.get('theme_colors', {})},
                  theme_fonts={**state.DEFAULT_THEME_FONTS,
                               **state.settings.get('theme_fonts', {})},
                  t=state._mobile_strings())


@router.get('/operator')
def route_operator(request: Request):
    sides      = int(state.settings.get('touchpad_sides', 1))
    split_step = 2 if sides == 1 else 1
    return render(request, 'operator.html',
                  num_lanes=int(state.settings.get('num_lanes', 8)),
                  split_step=split_step)


@router.get('/console')
def route_console(request: Request):
    return render(request, 'console.html',
                  num_lanes=max(int(state.settings.get('num_lanes', 8)), 12))


@router.get('/next_heats')
def route_next_heats(request: Request):
    return render(request, 'next_heats.html',
                  theme_colors={**state.DEFAULT_THEME_COLORS,
                                **state.settings.get('theme_colors', {})},
                  theme_fonts={**state.DEFAULT_THEME_FONTS,
                               **state.settings.get('theme_fonts', {})},
                  num_lanes=int(state.settings.get('num_lanes', 8)),
                  t=state._mobile_strings())


@router.get('/info')
def route_info(request: Request):
    return render(request, 'info.html')


@router.get('/help')
def route_help(request: Request):
    return render(request, 'help.html')
